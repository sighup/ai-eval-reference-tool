"""The provider contract: the SDK adapter, replay, and the network boundary.

The adapter is deterministic and worth pinning. The boundary is worth pinning
because being wrong about it costs money.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import NetworkTripwire, a_trace, sdk_message

from support_agent import config, model, replay, trace


def test_the_adapter_renumbers_tool_calls_and_maps_usage() -> None:
    """The API's ids are random per call. Putting them on the trace would mean two
    otherwise identical runs never compare clean."""
    provider = model.LiveProvider()
    turn = provider.adapt(
        sdk_message(
            stop_reason="tool_use",
            content=[
                {"type": "text", "text": "Let me look that up."},
                {
                    "type": "tool_use",
                    "id": "toolu_01A9tsvL3Bp2",
                    "name": "lookup_order",
                    "input": {"order_id": "A-3391"},
                },
                {"type": "tool_use", "id": "toolu_01Zz", "name": "lookup_order", "input": {}},
            ],
            usage={
                "input_tokens": 1203,
                "output_tokens": 88,
                "cache_read_input_tokens": 512,
                # Cache *creation* bills differently and is an artefact of when a
                # run happened rather than of what it did, so it is not recorded.
                "cache_creation_input_tokens": 64,
            },
        )
    )

    assert turn.text == "Let me look that up."
    assert [c.tool_call_id for c in turn.tool_calls] == ["tc-1", "tc-2"]
    assert turn.tool_calls[0].provider_id == "toolu_01A9tsvL3Bp2"
    assert "provider_id" not in turn.tool_calls[0].to_trace()
    assert turn.usage.to_trace() == {
        "input_tokens": 1203,
        "output_tokens": 88,
        "cached_tokens": 512,
    }

    # Numbering keeps counting across turns of one run; unknown block types are
    # ignored rather than mistaken for the model's answer; text blocks join.
    later = provider.adapt(
        sdk_message(content=[{"type": "text", "text": "A."}, {"type": "text", "text": "B."}])
    )
    assert later.text == "A.\n\nB."
    assert later.tool_calls == ()
    assert (
        provider.adapt(
            sdk_message(
                stop_reason="tool_use",
                content=[
                    {"type": "tool_use", "id": "toolu_x", "name": "issue_refund", "input": {}}
                ],
            )
        )
        .tool_calls[0]
        .tool_call_id
        == "tc-3"
    )


def test_every_terminal_sdk_stop_reason_is_in_the_schema_enum() -> None:
    """A stop reason the API can return and the schema rejects would fail at
    trace-write time, on a live run, after the money was spent."""
    sdk_reasons = {
        "end_turn",
        "max_tokens",
        "stop_sequence",
        "tool_use",
        "pause_turn",
        "refusal",
        "model_context_window_exceeded",
    }
    enum = set(trace._validator().schema["properties"]["stop_reason"]["enum"])

    assert (sdk_reasons - model.CONTINUE_REASONS) <= enum
    assert model.CONTINUE_REASONS.isdisjoint(enum)
    assert {"escalated", "max_steps"} <= enum


def test_a_live_run_checks_the_credential_before_constructing_a_client() -> None:
    provider = model.LiveProvider()
    assert provider._client is None

    with pytest.raises(config.MissingCredential) as caught:
        provider.next_turn("system", [{"role": "user", "content": "hi"}], [])
    # The message has to name the way out, or the first failure of a learner's
    # first command is a dead end.
    assert "--replay" in str(caught.value)


def test_the_client_constructor_is_the_next_thing_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a key present the tripwire fires, which proves the ordering above and
    locates the network boundary exactly, without a request leaving the machine."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")

    with pytest.raises(NetworkTripwire):
        model.LiveProvider().next_turn("system", [{"role": "user", "content": "hi"}], [])


def test_importing_the_replay_path_does_not_import_the_sdk() -> None:
    """Checked in a subprocess: this interpreter has already imported the SDK."""
    proof = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from support_agent import agent, cli, replay, tools, trace; "
            "print('anthropic' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proof.stdout.strip() == "False", proof.stdout


def test_replay_serves_recorded_turns_then_refuses() -> None:
    provider = replay.ReplayProvider(a_trace())
    assert provider.mode == "replay" and provider.remaining == 2

    first = provider.next_turn("system", [], [])
    assert first.stop_reason == "tool_use"
    assert first.tool_calls[0].tool_call_id == "tc-1"
    # No provider id: nothing here talks to a provider.
    assert first.tool_calls[0].provider_id is None
    # One usage object per run, so the whole recorded total lands on the first turn
    # and the accumulated figure matches the recording.
    assert first.usage.input_tokens == 1203

    second = provider.next_turn("system", [], [])
    assert second.stop_reason == "end_turn"
    assert second.usage.input_tokens == 0

    with pytest.raises(replay.ReplayExhausted, match="re-record"):
        provider.next_turn("system", [], [])


def test_replay_accepts_the_prompt_and_ignores_it() -> None:
    """This is the limit of replay, and the reason live is the default mode: edit
    the prompt, replay, and the recorded turns come back unchanged."""
    a = replay.ReplayProvider(a_trace()).next_turn("the original prompt", [], [])
    b = replay.ReplayProvider(a_trace()).next_turn("a completely different prompt", [], [])

    assert a == b


def test_replay_reproduces_the_configuration_the_recording_was_made_with() -> None:
    """Reporting today's ``--temperature`` over a recording made at a different one
    would be a claim the trace cannot support."""
    assert replay.ReplayProvider(a_trace(params={"max_tokens": 99, "temperature": 0.3})).params == {
        "max_tokens": 99,
        "temperature": 0.3,
    }


def test_a_loop_invented_stop_reason_replays_as_a_continue_reason() -> None:
    """``escalated`` and ``max_steps`` are the loop's words, not the model's. A turn
    that made tool calls stopped for ``tool_use``, whatever the run ended up
    recording, so the loop re-derives its own reason from what the tools did."""
    source = a_trace(
        stop_reason="escalated",
        steps=[
            {"step_id": 0, "source": "user", "message": "a person please", "rendered": "..."},
            {
                "step_id": 1,
                "source": "agent",
                "message": "Passing you to a specialist.",
                "tool_calls": [
                    {
                        "tool_call_id": "tc-1",
                        "name": "escalate_to_human",
                        "arguments": {"reason": "asked", "summary": "s", "priority": "normal"},
                    }
                ],
            },
        ],
    )

    (only,) = replay._turns_from(source)
    assert only.stop_reason == "tool_use"


def test_loading_a_multi_fixture_recording_requires_a_choice(tmp_path) -> None:
    path = tmp_path / "many.jsonl"
    trace.write(a_trace(fixture_id="refund-outside-window"), path)
    trace.write(a_trace(fixture_id="order-status"), path)

    with pytest.raises(replay.ReplayExhausted, match="pass fixture_id"):
        replay.ReplayProvider.from_file(path)
    assert replay.ReplayProvider.from_file(path, fixture_id="order-status").fixture_id == (
        "order-status"
    )
