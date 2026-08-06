"""Loading, rendering and fingerprinting the prompt templates.

The prompts live in ``prompts/*.md`` rather than in this file. They are text that
gets edited and re-edited, and a template in a Python string literal is a template
nobody can diff cleanly or review as prose.

Two templates, both editable:

* ``system.md`` — the agent's instructions. Rendered once per run.
* ``context.md`` — the wrapper that carries the retrieved policy excerpts and the
  customer's message into the user turn. Rendered once per user turn.

Substitution is ``{{name}}`` and nothing else: no expressions, no conditionals, no
loops. A template language would be one more thing that can go wrong between an
edit and a behaviour change, and the whole value of these files is that what you
read is what the model got.

Rendering is a pure function of its arguments. Nothing here reads the clock, the
environment, or anything not passed in, so the same fixture and corpus produce the
same prompt on every machine — which is what makes a behaviour change attributable
to the edit that caused it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import config

SYSTEM_TEMPLATE = "system.md"
CONTEXT_TEMPLATE = "context.md"

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class UnrenderedPlaceholder(ValueError):
    """A ``{{name}}`` survived rendering.

    Raised rather than sent. An unsubstituted placeholder reaching the model is
    the kind of failure that produces a plausible-looking answer built on a
    literal ``{{customer_id}}``, and it is much cheaper to catch here.
    """


def template_path(name: str) -> Path:
    return config.project_root() / "prompts" / name


def load_template(name: str) -> str:
    path = template_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"Missing prompt template: {path}")
    return path.read_text(encoding="utf-8")


def render(template: str, values: dict[str, Any]) -> str:
    """Substitute every ``{{name}}`` in ``template``.

    Unknown placeholders are an error, not a silent empty string: a prompt that
    quietly loses a section is harder to debug than one that refuses to render.
    """
    missing: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.append(key)
            return match.group(0)
        return str(values[key])

    rendered = _PLACEHOLDER.sub(substitute, template)
    if missing:
        raise UnrenderedPlaceholder(
            f"No value supplied for {{{{{', '.join(sorted(set(missing)))}}}}}. "
            f"Placeholders available: {', '.join(sorted(values))}."
        )
    return rendered


def render_system(customer_id: str, session_id: str, as_of: str) -> str:
    """The system prompt for one run."""
    return render(
        load_template(SYSTEM_TEMPLATE),
        {"as_of_date": as_of, "customer_id": customer_id, "session_id": session_id},
    )


def format_documents(retrieved: list[dict[str, Any]]) -> str:
    """Lay the retrieved documents out for the context template.

    The ``doc_id`` is included so the model can cite it and a scorer can check
    the citation against the ``retrieved`` list on the same step.
    """
    if not retrieved:
        return "(No policy excerpts matched this message.)"
    blocks = [f'<document id="{hit["doc_id"]}">\n{hit["text"]}\n</document>' for hit in retrieved]
    return "\n\n".join(blocks)


def render_context(message: str, retrieved: list[dict[str, Any]]) -> str:
    """The user-turn content for one message, with its retrieved excerpts."""
    return render(
        load_template(CONTEXT_TEMPLATE),
        {"documents": format_documents(retrieved), "message": message},
    )


# --------------------------------------------------------------------------- #
# Fingerprints
# --------------------------------------------------------------------------- #


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prompt_fingerprint() -> str:
    """Digest of both template sources.

    Over the *sources*, not a rendered result: two runs of different fixtures
    share a prompt version but not a rendered prompt, and the question this
    answers is "same prompt version?".
    """
    return _sha256(load_template(SYSTEM_TEMPLATE) + "\0" + load_template(CONTEXT_TEMPLATE))


def tools_fingerprint(tool_schemas: list[dict[str, Any]]) -> str:
    """Digest of the tool definitions as sent, including their descriptions."""
    return _sha256(json.dumps(tool_schemas, sort_keys=True, ensure_ascii=False))


def corpus_fingerprint() -> str:
    """Digest of every corpus document, by id and content.

    The whole corpus rather than the retrieved subset: editing any document can
    change what retrieval returns for an unrelated message.
    """
    from .retrieve import load_corpus

    payload = "\0".join(f"{doc.doc_id}\n{doc.text}" for doc in load_corpus())
    return _sha256(payload)


def fingerprint(tool_schemas: list[dict[str, Any]]) -> dict[str, str]:
    """The trace's ``fingerprint`` object, in schema key order."""
    return {
        "prompt_sha256": prompt_fingerprint(),
        "tools_sha256": tools_fingerprint(tool_schemas),
        "corpus_sha256": corpus_fingerprint(),
    }
