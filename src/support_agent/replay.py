"""Replay a recorded trace as if it were the model.

Replay is **not** how the agent is normally run — that is a live call, because the
whole point of changing a prompt or a tool is to find out what the model does
differently. Replay exists to hold the agent still.

When you are writing something that judges a trace, a live run gives you a moving
target: the judge disagrees with its previous verdict and you cannot tell whether
your judge changed or the agent did. Replaying a fixed recording removes one of
those variables. The agent's output is pinned, so any change in the verdict came
from the judge.

It satisfies the same :class:`~support_agent.model.Provider` contract as the live
path, so everything downstream of the model call — retrieval, prompt assembly,
tool dispatch, side effects, trace writing — is the real code rather than a
parallel fake of it.

No HTTP client is constructed here and the ``anthropic`` package is never
imported, so replay cannot make a billable call. Running past the end of a
recording raises :class:`ReplayExhausted` rather than quietly falling through to
the API.

Two things are not replayed:

* **Retrieval is re-run, not replayed.** The corpus is on disk and BM25 is
  deterministic, so the agent recomputes it. If a corpus edit changes what gets
  retrieved, the replayed trace changes with it.
* **Usage is reproduced in total, not per turn.** The trace records one ``usage``
  object per run, so there is nothing to attribute to individual turns; the
  recorded total is emitted on the first turn and zeros thereafter, which makes
  the accumulated total match. This is why ``usage`` and ``cost_usd`` are in
  ``trace.VOLATILE_FIELDS``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import config, trace
from .model import THINKING_DISABLED, ModelTurn, ToolCall, Usage


class ReplayExhausted(RuntimeError):
    """The loop asked for more turns than the recording contains.

    Raised rather than falling back to the network. If you see this, the run
    diverged from the recording — usually a changed prompt, a changed corpus, or a
    tool that now errors where it previously succeeded — and the fix is to
    re-record, not to go live.
    """


class ReplayProvider:
    """Serve the agent turns of a recorded trace, in order."""

    mode = "replay"

    def __init__(self, recording: dict[str, Any]) -> None:
        self.recording = recording
        self.fixture_id = recording.get("fixture_id", "<unknown>")
        self.model = recording.get("model", "")
        self._turns = _turns_from(recording)
        self._index = 0

    @property
    def params(self) -> dict[str, Any]:
        """The parameters the *recording* was made with, not the current defaults.

        The turns came from that request, so those are the parameters that
        produced them. Reporting today's ``--temperature`` over a recording made
        at a different one would be a claim the trace cannot support.
        """
        recorded = self.recording.get("params")
        if isinstance(recorded, dict):
            return dict(recorded)
        return {
            "max_tokens": config.MAX_TOKENS,
            "temperature": config.TEMPERATURE,
            "thinking": dict(THINKING_DISABLED),
        }

    @classmethod
    def from_file(cls, path: Path, fixture_id: str | None = None) -> ReplayProvider:
        """Load a recording from a JSONL trace file.

        A file with one trace is used as-is. A file with several requires
        ``fixture_id`` to disambiguate, so the choice is never implicit.
        """
        traces = trace.read(path)
        if not traces:
            raise ReplayExhausted(f"No traces in {path}")
        if fixture_id is not None:
            matches = [t for t in traces if t.get("fixture_id") == fixture_id]
            if not matches:
                available = ", ".join(sorted({str(t.get("fixture_id")) for t in traces}))
                raise ReplayExhausted(
                    f"No recording for fixture {fixture_id!r} in {path}. Found: {available}"
                )
            return cls(matches[-1])
        if len(traces) > 1:
            raise ReplayExhausted(
                f"{path} holds {len(traces)} traces; pass fixture_id to choose one."
            )
        return cls(traces[0])

    @property
    def remaining(self) -> int:
        return len(self._turns) - self._index

    def next_turn(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        """Return the next recorded turn.

        The arguments are accepted and ignored. They are what the live provider
        would send, and the loop builds them identically in both modes, but a
        recording cannot answer a prompt it never saw.

        This is the limit of replay, and worth being blunt about: **edit the
        prompt and replay will not notice.** The recorded turns come back
        unchanged. To find out what a prompt edit did, run live.
        """
        if self._index >= len(self._turns):
            raise ReplayExhausted(
                f"Recording for fixture {self.fixture_id!r} has {len(self._turns)} agent "
                f"turn(s) and the loop asked for turn {self._index + 1}. The run has "
                "diverged from the recording; re-record it rather than going live."
            )
        turn = self._turns[self._index]
        self._index += 1
        return turn


def _turns_from(recording: dict[str, Any]) -> tuple[ModelTurn, ...]:
    """Rebuild one ModelTurn per recorded agent step."""
    agent_steps = [step for step in recording.get("steps", []) if step.get("source") == "agent"]
    if not agent_steps:
        raise ReplayExhausted(
            f"Recording for fixture {recording.get('fixture_id')!r} contains no agent steps. "
            "A trace with no agent turn cannot be replayed."
        )
    final_reason = recording.get("stop_reason", "end_turn")
    recorded_usage = recording.get("usage") or {}

    turns: list[ModelTurn] = []
    for position, step in enumerate(agent_steps):
        is_last = position == len(agent_steps) - 1
        calls = tuple(
            ToolCall(
                tool_call_id=call["tool_call_id"],
                name=call["name"],
                arguments=call.get("arguments", {}),
                # No provider id: nothing here talks to a provider. The loop uses
                # this to build tool_result blocks and falls back to tool_call_id.
                provider_id=None,
            )
            for call in step.get("tool_calls", [])
        )

        # Per-turn stop reasons are not recorded, and do not need to be. A turn
        # with tool calls always stopped for tool_use; a turn without them is the
        # last one, and the run's stop reason is that turn's stop reason. The
        # terminal reasons the loop invents itself — escalated, max_steps — arrive
        # on a turn that did make tool calls, so they resolve to tool_use here and
        # the loop re-derives them from what the tools did.
        if calls:
            stop_reason = "tool_use"
        elif is_last:
            loop_invented = final_reason in {"escalated", "max_steps"}
            stop_reason = "end_turn" if loop_invented else final_reason
        else:
            stop_reason = "end_turn"

        turns.append(
            ModelTurn(
                text=step.get("message", ""),
                stop_reason=stop_reason,
                tool_calls=calls,
                # The whole recorded total lands on the first turn so the
                # accumulated figure matches; see the module docstring.
                usage=Usage(**recorded_usage) if position == 0 and recorded_usage else Usage(),
            )
        )
    return tuple(turns)
