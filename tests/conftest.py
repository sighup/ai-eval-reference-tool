"""Shared fixtures, and the guards that keep the suite offline.

The suite is small on purpose. It covers the deterministic parts — retrieval,
template rendering, the trace contract, tool dispatch, the SDK adapter — plus two
tests that run a whole pipeline end to end. It does not try to characterise what
the model does, because measuring model behaviour is what you are here to build.

Every test runs with the network boundary sealed and the run directory redirected
into a temporary path. Both are autouse, because both have to be true by default
rather than remembered.

**Unsetting ``ANTHROPIC_API_KEY`` is not enough.** ``config.api_key()`` calls
``config.load_env()``, which reloads the key from ``reference-tool/.env`` — so a
test that only clears the environment will happily make a real, billable call on
the machine of anyone who has a key on disk. Both guards are needed: a neutralised
loader *and* a client constructor that refuses to be built.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import pytest

from support_agent import config, model


class NetworkTripwire(RuntimeError):
    """An HTTP client was constructed. Nothing in this suite may do that."""


def _tripwire(*args: Any, **kwargs: Any) -> Any:
    raise NetworkTripwire("anthropic.Anthropic() was constructed inside the test suite.")


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setattr(anthropic, "Anthropic", _tripwire)


@pytest.fixture(autouse=True)
def isolated_runs(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: Any) -> None:
    """Point ``runs/`` at a temporary directory so the suite leaves nothing behind."""
    target = tmp_path_factory.mktemp("runs")
    monkeypatch.setattr(config, "runs_dir", lambda: target)


def sdk_message(**overrides: Any) -> anthropic.types.Message:
    """A real ``anthropic.types.Message``, built through the SDK's own validator.

    Built rather than mocked, so the adapter is checked against the SDK's models
    instead of against our memory of them — which is what keeps the live path
    honest while it is developed with no key.
    """
    payload: dict[str, Any] = {
        "id": "msg_01XyZ",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "content": [{"type": "text", "text": "Hello."}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    payload.update(overrides)
    return anthropic.types.Message.model_validate(payload)


def a_trace(**overrides: Any) -> dict[str, Any]:
    """A schema-valid trace, for use as a replay source or a validator subject."""
    message = "I want a refund for order A-3391."
    trace: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": "run-refund-outside-window-01",
        "timestamp": "2026-07-29T14:02:11+00:00",
        "fixture_id": "refund-outside-window",
        "mode": "live",
        "model": "claude-sonnet-5",
        "params": {"max_tokens": 2048, "temperature": 1.0, "thinking": {"type": "disabled"}},
        "provider": "anthropic",
        "prompt": {"system": "You are a support agent.", "tools": []},
        "fingerprint": {
            "prompt_sha256": "a" * 64,
            "tools_sha256": "b" * 64,
            "corpus_sha256": "c" * 64,
        },
        "input": {"customer_id": "cust-1042", "session_id": "sess-0088", "message": message},
        "steps": [
            {
                "step_id": 0,
                "source": "user",
                "message": message,
                "retrieved": [{"doc_id": "kb-returns-01", "score": 0.62, "text": "30 days."}],
                "rendered": f"docs\n\n{message}",
            },
            {
                "step_id": 1,
                "source": "agent",
                "message": "Checking that order.",
                "tool_calls": [
                    {
                        "tool_call_id": "tc-1",
                        "name": "lookup_order",
                        "arguments": {"order_id": "A-3391"},
                    }
                ],
            },
            {
                "step_id": 2,
                "source": "system",
                "observations": [
                    {"source_call_id": "tc-1", "content": {"ok": True}, "is_error": False}
                ],
            },
            {"step_id": 3, "source": "agent", "message": "Outside the 30-day window."},
        ],
        "final_output": "Outside the 30-day window.",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1203, "output_tokens": 88, "cached_tokens": 0},
        "cost_usd": 0.004929,
        "labels": {},
    }
    trace.update(overrides)
    return trace


class ScriptedProvider:
    """Serves a fixed list of turns and remembers the requests it was handed.

    Satisfies the same contract as the live and replay providers, so the pipeline
    test exercises the real loop rather than an imitation of it.
    """

    mode = "live"

    def __init__(self, turns: list[model.ModelTurn]) -> None:
        self.turns = list(turns)
        self.model = "claude-sonnet-5"
        self.requests: list[list[dict[str, Any]]] = []

    @property
    def params(self) -> dict[str, Any]:
        return {
            "max_tokens": config.MAX_TOKENS,
            "temperature": config.TEMPERATURE,
            "thinking": {"type": "disabled"},
        }

    def next_turn(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> model.ModelTurn:
        # Deep-copied so a later mutation of ``messages`` cannot rewrite history.
        self.requests.append(json.loads(json.dumps(messages)))
        if not self.turns:
            raise AssertionError("the loop asked for more turns than the script holds")
        return self.turns.pop(0)
