"""The trace contract: writer, reader, validator, and a behavioural diff.

This module owns the schema. One JSON object per agent run, one run per line in
a JSONL file — so a scorer's first line of code can be ``json.loads(line)``.

A trace is **self-contained**. The rendered system prompt, the tool definitions as
sent, the retrieval result, and the rendered user content are all recorded
verbatim, so scoring a run needs the trace and nothing else. That matters because
the agent is meant to be edited: by the time you are comparing last Tuesday's runs
against today's, the working tree that produced them is long gone.

Two properties are load-bearing:

* **Fixed key order.** Every dict below is built in the order the schema lists,
  and ``json.dumps`` is called without ``sort_keys``, so the bytes are stable.
* **Fixed float precision.** BM25 scores and ``cost_usd`` are rounded at the
  point of construction, not at serialisation time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import config


class TraceValidationError(ValueError):
    """A trace did not validate against ``schema/trace-v1.json``."""


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(config.schema_path().read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate(trace: dict[str, Any]) -> None:
    """Raise :class:`TraceValidationError` if ``trace`` is off-contract.

    Called on every written trace. This is a guardrail for whoever is editing the
    agent: when a change to a tool or a step breaks the shape that scorers depend
    on, it fails at write time instead of surfacing as a confusing scorer bug
    three days later.
    """
    errors = sorted(_validator().iter_errors(trace), key=lambda e: list(e.absolute_path))
    if errors:
        detail = "\n".join(
            f"  {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in errors[:10]
        )
        raise TraceValidationError(f"Trace does not match trace-v1.json:\n{detail}")


def dumps(trace: dict[str, Any]) -> str:
    """Serialise one trace to a single line, preserving insertion order."""
    return json.dumps(trace, ensure_ascii=False, separators=(",", ": "))


def write(trace: dict[str, Any], path: Path) -> Path:
    """Validate, then append ``trace`` as one line of JSONL."""
    validate(trace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(dumps(trace) + "\n")
    return path


def read(path: Path) -> list[dict[str, Any]]:
    """Read every run from a JSONL trace file, skipping blank lines."""
    traces = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            traces.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno} is not valid JSON: {exc}") from exc
    return traces


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #

#: Fields that differ between two runs for reasons that are not behaviour. Token
#: counts, cost and the clock are properties of when and how a call was made, and
#: ``run_id`` carries a repeat index so two runs of one fixture always differ in
#: it. ``fingerprint`` is deliberately absent: it is the independent variable, and
#: a comparison that hid a prompt change would be worse than useless.
VOLATILE_FIELDS = ("run_id", "timestamp", "mode", "usage", "cost_usd")


def normalise(trace: dict[str, Any]) -> dict[str, Any]:
    """Drop the volatile fields so two traces can be compared on behaviour."""
    return {k: v for k, v in trace.items() if k not in VOLATILE_FIELDS}


def diff(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """Behavioural differences between two runs.

    Not a text diff. Two live runs of the same prompt phrase the same decision
    differently every time, so diffing prose would bury the signal in wording.
    What this reports is what the agent *did*: which configuration produced it,
    which tools it called with which arguments, what retrieval fed it, why it
    stopped, and whether the answer text changed at all. Judging whether a changed
    answer is better is a scorer's job, not this function's.

    Returns an empty list when the two runs are behaviourally identical.
    """
    out: list[str] = []
    out.extend(_diff_fingerprint(left.get("fingerprint"), right.get("fingerprint")))

    for key in ("fixture_id", "model", "stop_reason"):
        if left.get(key) != right.get(key):
            out.append(f"~ {key}: {left.get(key)!r} -> {right.get(key)!r}")

    out.extend(_diff_params(left.get("params") or {}, right.get("params") or {}))

    if _system_prompt(left) != _system_prompt(right):
        out.append("~ prompt.system: rendered system prompt changed")
    out.extend(_diff_tool_defs(left.get("prompt", {}), right.get("prompt", {})))

    out.extend(_diff_retrieval(left.get("steps", []), right.get("steps", [])))
    out.extend(_diff_tool_calls(left.get("steps", []), right.get("steps", [])))

    if left.get("final_output") != right.get("final_output"):
        out.append(
            "~ final_output: changed "
            f"({len(left.get('final_output', ''))} -> {len(right.get('final_output', ''))} chars)"
        )

    if left.get("labels") != right.get("labels"):
        out.append("~ labels: changed")

    return out


def _system_prompt(trace: dict[str, Any]) -> str:
    return trace.get("prompt", {}).get("system", "")


def _diff_fingerprint(left: Any, right: Any) -> list[str]:
    """Report which editable surface changed, which is what attributes a result."""
    if left == right:
        return []
    if not isinstance(left, dict) or not isinstance(right, dict):
        return ["~ fingerprint: changed"]
    labels = {
        "prompt_sha256": "prompt templates",
        "tools_sha256": "tool definitions",
        "corpus_sha256": "corpus",
    }
    changed = [label for key, label in labels.items() if left.get(key) != right.get(key)]
    unchanged = [label for key, label in labels.items() if left.get(key) == right.get(key)]
    out = [f"~ fingerprint: {', '.join(changed)} changed"]
    if unchanged:
        out.append(f"  (unchanged: {', '.join(unchanged)})")
    return out


def _diff_params(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """Report changed request parameters key by key.

    Reported rather than normalised away: turning the temperature down is one of
    the interventions worth making, and a comparison that hid it would credit the
    result to whatever else changed.
    """
    return [
        f"~ params.{key}: {left.get(key)!r} -> {right.get(key)!r}"
        for key in sorted(set(left) | set(right), key=str)
        if left.get(key) != right.get(key)
    ]


def _diff_tool_defs(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    before = {t.get("name"): t for t in left.get("tools", [])}
    after = {t.get("name"): t for t in right.get("tools", [])}
    out: list[str] = []
    for name in sorted(set(before) | set(after), key=str):
        if name not in before:
            out.append(f"+ prompt.tools[{name}]: tool added")
        elif name not in after:
            out.append(f"- prompt.tools[{name}]: tool removed")
        elif before[name] != after[name]:
            detail = []
            if before[name].get("description") != after[name].get("description"):
                detail.append("description")
            if before[name].get("input_schema") != after[name].get("input_schema"):
                detail.append("input_schema")
            out.append(f"~ prompt.tools[{name}]: {' and '.join(detail) or 'definition'} changed")
    return out


def _retrievals(steps: list[dict[str, Any]]) -> list[list[str]]:
    return [
        [hit.get("doc_id", "") for hit in step.get("retrieved", [])]
        for step in steps
        if step.get("source") == "user" and "retrieved" in step
    ]


def _diff_retrieval(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[str]:
    before, after = _retrievals(left), _retrievals(right)
    if before == after:
        return []
    out = []
    for i in range(max(len(before), len(after))):
        a = before[i] if i < len(before) else None
        b = after[i] if i < len(after) else None
        if a != b:
            out.append(f"~ retrieved[turn {i}]: {a} -> {b}")
    return out


def _call_signature(steps: list[dict[str, Any]]) -> list[str]:
    out = []
    for step in steps:
        if step.get("source") != "agent":
            continue
        for call in step.get("tool_calls", []):
            arguments = json.dumps(call.get("arguments", {}), sort_keys=True, ensure_ascii=False)
            out.append(f"{call.get('name')}({arguments})")
    return out


def _diff_tool_calls(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[str]:
    before, after = _call_signature(left), _call_signature(right)
    if before == after:
        return []
    out = [f"~ tool_calls: {len(before)} call(s) -> {len(after)} call(s)"]
    for i in range(max(len(before), len(after))):
        a = before[i] if i < len(before) else "(none)"
        b = after[i] if i < len(after) else "(none)"
        if a != b:
            out.append(f"  [{i}] {a} -> {b}")
    return out


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def run_id_for(fixture_id: str, index: int = 1) -> str:
    """Derive a run id from a fixture id and a repeat index.

    The index is what keeps repeated runs of one fixture apart. Without it every
    run of a fixture would share a ``runs/<run_id>/`` directory and each would
    delete the side effects of the one before it — which is exactly the evidence
    you need when the question is how *often* the agent does something rather than
    whether it can.
    """
    return f"run-{fixture_id}-{index:02d}"


def utc_now() -> str:
    """Wall-clock time, in the one place that is allowed to read it.

    Only ``timestamp`` uses this, and ``timestamp`` is volatile. Everything that
    affects behaviour — the agent's notion of today included — comes from
    ``config.AS_OF_DATE`` instead, so a run means the same thing on any day.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
class TraceBuilder:
    """Accumulates steps, then emits the trace dict in fixed key order."""

    run_id: str
    fixture_id: str
    mode: str
    model: str
    params: dict[str, Any]
    customer_id: str
    session_id: str
    message: str
    system_prompt: str
    tool_schemas: list[dict[str, Any]]
    fingerprint: dict[str, str]
    timestamp: str = field(default_factory=utc_now)
    steps: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def _next_step_id(self) -> int:
        return len(self.steps)

    def add_user_step(
        self,
        message: str,
        rendered: str,
        retrieved: list[dict[str, Any]] | None = None,
    ) -> None:
        """Record one user turn: the raw message, what was retrieved, what was sent."""
        step: dict[str, Any] = {
            "step_id": self._next_step_id(),
            "source": "user",
            "message": message,
        }
        # Omitted rather than null when retrieval did not run, so a scorer can
        # test presence.
        if retrieved is not None:
            step["retrieved"] = retrieved
        step["rendered"] = rendered
        self.steps.append(step)

    def add_agent_step(
        self,
        message: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        step: dict[str, Any] = {
            "step_id": self._next_step_id(),
            "source": "agent",
            "message": message,
        }
        if tool_calls is not None:
            step["tool_calls"] = tool_calls
        self.steps.append(step)

    def add_system_step(self, observations: list[dict[str, Any]]) -> None:
        self.steps.append(
            {
                "step_id": self._next_step_id(),
                "source": "system",
                "observations": observations,
            }
        )

    def add_usage(self, input_tokens: int, output_tokens: int, cached_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cached_tokens += cached_tokens

    def build(self, final_output: str, stop_reason: str) -> dict[str, Any]:
        """Emit the trace. Key order here *is* the contract."""
        return {
            "schema_version": config.SCHEMA_VERSION,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "fixture_id": self.fixture_id,
            "mode": self.mode,
            "model": self.model,
            "params": self.params,
            "provider": config.PROVIDER,
            "prompt": {
                "system": self.system_prompt,
                "tools": self.tool_schemas,
            },
            "fingerprint": self.fingerprint,
            "input": {
                "customer_id": self.customer_id,
                "session_id": self.session_id,
                "message": self.message,
            },
            "steps": self.steps,
            "final_output": final_output,
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cached_tokens": self.cached_tokens,
            },
            "cost_usd": config.cost_usd(
                self.model, self.input_tokens, self.output_tokens, self.cached_tokens
            ),
            # Reserved for whoever is scoring. The agent never writes to it.
            "labels": {},
        }
