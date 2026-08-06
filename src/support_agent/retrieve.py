"""BM25 retrieval over the local Markdown corpus.

Retrieval runs **automatically once per user turn**, before the model call. It is
deliberately not one of the three tools, for two reasons:

1. The retrieval leg has to be inspectable separately from generation, which
   needs document ids and scores as first-class trace fields — not buried inside
   a tool observation the model chose to make.
2. Corpus text must always enter the context. If retrieval were a tool the model
   could decline to call it.

The ranking function is hand-written Okapi BM25, about thirty lines. A library
would be shorter, but ``score`` reaches the trace and gets reasoned about, so it
needs to be readable here and identical on every machine.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import config

# Standard Okapi parameters. Fixed rather than tuned: lexical retrieval over a
# small corpus returns the wrong document sometimes, and that is worth seeing.
K1 = 1.5
B = 0.75

_TOKEN = re.compile(r"[a-z0-9]+")

#: Dropped from both documents and queries before scoring.
#:
#: Without this, ranking is decided by stopwords rather than by content. A
#: customer asking "Where is my order? It has not arrived." matches documents on
#: "it" and "has" — which together outweighed every content term — while the
#: words that actually carry the question, "where" and "my", appear in no
#: document at all. The result was that a shipping question retrieved no shipping
#: document.
#:
#: This is not an attempt at good retrieval. The list is short, there is no
#: stemming and no synonyms, so "zip" will not match "zipper" and a
#: partially-relevant document still wins sometimes. Those are the ordinary
#: limits of lexical matching. Being driven by "it" and "has" is not; it is noise.
STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can cannot could did do does doing
    for from had has have how i if in into is it its me my no not of on or
    should so t s that the their them then there these they this those to
    was were what when where which who will with would you your
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase, split on anything that is not a letter or digit, drop stopwords."""
    return [term for term in _TOKEN.findall(text.lower()) if term not in STOPWORDS]


@dataclass(frozen=True)
class Document:
    doc_id: str
    text: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class Hit:
    doc_id: str
    score: float
    text: str

    def to_trace(self) -> dict[str, object]:
        """The shape this takes on the trace, in schema key order."""
        return {"doc_id": self.doc_id, "score": self.score, "text": self.text}


def load_corpus(directory: Path | None = None) -> list[Document]:
    """Load every ``*.md`` file, sorted by filename so document order is fixed."""
    directory = directory or config.corpus_dir()
    if not directory.is_dir():
        raise FileNotFoundError(f"Corpus directory not found: {directory}")
    docs = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        docs.append(Document(doc_id=path.stem, text=text, tokens=tuple(tokenize(text))))
    if not docs:
        raise FileNotFoundError(f"No Markdown documents in {directory}")
    return docs


class Bm25Index:
    """An in-memory BM25 index over the corpus."""

    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self.n = len(documents)
        self.avgdl = sum(len(d.tokens) for d in documents) / self.n
        # Document frequency per term.
        self.df: dict[str, int] = {}
        for doc in documents:
            for term in set(doc.tokens):
                self.df[term] = self.df.get(term, 0) + 1

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def _score(self, query_terms: list[str], doc: Document) -> float:
        dl = len(doc.tokens)
        score = 0.0
        for term in set(query_terms):
            tf = doc.tokens.count(term)
            if not tf:
                continue
            denominator = tf + K1 * (1 - B + B * dl / self.avgdl)
            score += self._idf(term) * (tf * (K1 + 1)) / denominator
        return score

    def search(self, query: str, top_k: int = config.RETRIEVAL_TOP_K) -> list[Hit]:
        """Top ``top_k`` documents for ``query``.

        Ties break on ``doc_id`` ascending, so an identical query always returns
        an identical ordering. Scores are rounded at construction, which is what
        keeps the trace stable under re-serialisation.
        """
        terms = tokenize(query)
        scored = [
            Hit(
                doc_id=doc.doc_id,
                score=round(self._score(terms, doc), config.SCORE_PRECISION),
                text=doc.text,
            )
            for doc in self.documents
        ]
        scored.sort(key=lambda hit: (-hit.score, hit.doc_id))
        return scored[:top_k]


@lru_cache(maxsize=4)
def _cached_index(directory: str) -> Bm25Index:
    return Bm25Index(load_corpus(Path(directory)))


def retrieve(
    query: str,
    top_k: int = config.RETRIEVAL_TOP_K,
    directory: Path | None = None,
) -> list[Hit]:
    """Retrieve the top ``top_k`` corpus documents for a user message."""
    directory = directory or config.corpus_dir()
    return _cached_index(str(directory)).search(query, top_k=top_k)
