"""BM25 is a pure function of the corpus and the message.

That property is what lets a changed output be attributed to the model rather than
to the inputs having drifted, so it is tested directly rather than assumed.

Nothing here asserts that a particular query returns a particular document. Lexical
retrieval over a small corpus returns the wrong document sometimes, and that is a
failure mode worth having rather than a bug to pin down.
"""

from __future__ import annotations

import json

from support_agent import config, retrieve


def test_retrieval_is_deterministic() -> None:
    query = "I want a refund for order A-3391."

    first = [hit.to_trace() for hit in retrieve.retrieve(query)]
    repeat = [hit.to_trace() for hit in retrieve.retrieve(query)]
    # A fresh index, bypassing the cache: the lru_cache has to be an optimisation
    # rather than a source of truth.
    fresh = [hit.to_trace() for hit in retrieve.Bm25Index(retrieve.load_corpus()).search(query)]

    assert json.dumps(first) == json.dumps(repeat) == json.dumps(fresh)
    assert list(first[0]) == ["doc_id", "score", "text"]


def test_ties_break_on_doc_id_ascending() -> None:
    """A query matching nothing scores every document zero.

    Without a total order the ranking of an all-zero result depends on filesystem
    iteration order, and two runs of one fixture stop matching.
    """
    hits = retrieve.retrieve("zzzz qqqq", top_k=99)

    assert all(hit.score == 0.0 for hit in hits)
    assert [hit.doc_id for hit in hits] == sorted(hit.doc_id for hit in hits)


def test_scores_are_rounded_at_construction() -> None:
    """Rounded on the way in, not at serialisation time, so a frozen trace
    re-serialises byte for byte."""
    hits = retrieve.retrieve("delivery tracking parcel", top_k=99)

    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)
    assert all(hit.score == round(hit.score, config.SCORE_PRECISION) for hit in hits)


def test_stopwords_are_dropped_from_both_sides() -> None:
    """Without this, ranking is decided by 'it' and 'has' rather than by content."""
    assert retrieve.tokenize("Where is my order? It has not arrived.") == ["order", "arrived"]
