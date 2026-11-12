"""The tool-use loop: one fixture in, one trace out.

This is the whole agent. Everything else in the package is a part it uses —
retrieval, prompt rendering, the provider, the tools, the trace writer — and this
module is the only place that decides what happens next.

The shape of one run:

1. Reset ``runs/<run_id>/`` so the side effects on disk describe this run alone.
2. Render the system prompt from ``prompts/system.md``.
3. For the user's message: retrieve, render ``prompts/context.md`` around the
   result, and record a **user step** carrying the raw message, what retrieval
   returned, and the content that was actually sent. A user step is everything
   that went in.
4. Ask the provider for a turn. Repeat until something terminal happens.
5. Build the trace and hand it back. Writing it is the caller's job.

The loop is written against :class:`~support_agent.model.Provider`, so it does not
know or care whether the turns come from the API or from a recording. That is what
makes a replayed run the same code path as a live one rather than a parallel
imitation of it.

Nothing here reads the clock. The agent's notion of today is ``as_of``, which the
caller passes in and which defaults to the pinned ``config.AS_OF_DATE``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config, prompts, retrieve, tools, trace
from .model import ModelTurn, Provider


class FixtureError(ValueError):
    """A fixture file is missing a field, or is not a JSON object."""


#: The fields every fixture carries. Inputs, not rendered prompts: the prompt is
#: re-rendered at run time so an edit to a template shows up in the next run
#: without the fixtures being touched.
FIXTURE_FIELDS = ("fixture_id", "customer_id", "session_id", "message")


@dataclass(frozen=True)
class Fixture:
    """One run's input."""

    fixture_id: str
    customer_id: str
    session_id: str
    message: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any], source: str = "<dict>") -> Fixture:
        missing = [field for field in FIXTURE_FIELDS if not payload.get(field)]
        if missing:
            raise FixtureError(f"{source}: fixture is missing {', '.join(missing)}")
        return cls(**{field: str(payload[field]) for field in FIXTURE_FIELDS})

    @classmethod
    def from_file(cls, path: Path) -> Fixture:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FixtureError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise FixtureError(f"{path} must hold a JSON object, not a {type(payload).__name__}")
        return cls.from_dict(payload, source=str(path))


def run(
    fixture: Fixture,
    provider: Provider,
    *,
    run_id: str,
    as_of: str = config.AS_OF_DATE,
    max_steps: int = config.DEFAULT_MAX_STEPS,
    tool_schemas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run ``fixture`` to completion and return its trace.

    Returns the trace rather than writing it, so a caller can inspect a run
    without leaving a file behind, and so the decision about which file a run
    accumulates into stays with the CLI.
    """
    tool_schemas = tools.tool_schemas() if tool_schemas is None else tool_schemas
    tools.reset_run_dir(run_id)

    session = tools.Session(
        run_id=run_id,
        customer_id=fixture.customer_id,
        session_id=fixture.session_id,
        as_of=as_of,
    )
    system = prompts.render_system(fixture.customer_id, fixture.session_id, as_of)

    builder = trace.TraceBuilder(
        run_id=run_id,
        fixture_id=fixture.fixture_id,
        mode=provider.mode,
        model=provider.model,
        params=provider.params,
        customer_id=fixture.customer_id,
        session_id=fixture.session_id,
        message=fixture.message,
        system_prompt=system,
        tool_schemas=tool_schemas,
        fingerprint=prompts.fingerprint(tool_schemas),
    )

    # The one user turn. Retrieval runs here, before the model call, so corpus
    # text cannot fail to enter the context.
    retrieved = [hit.to_trace() for hit in retrieve.retrieve(fixture.message)]
    rendered = prompts.render_context(fixture.message, retrieved)
    builder.add_user_step(fixture.message, rendered, retrieved=retrieved)

    messages: list[dict[str, Any]] = [{"role": "user", "content": rendered}]
    final_output = ""
    stop_reason = "max_steps"

    for _ in range(max_steps):
        turn = provider.next_turn(system, messages, tool_schemas)
        builder.add_usage(
            turn.usage.input_tokens, turn.usage.output_tokens, turn.usage.cached_tokens
        )

        if turn.wants_tools:
            builder.add_agent_step(
                turn.text, tool_calls=[call.to_trace() for call in turn.tool_calls]
            )
            messages.append({"role": "assistant", "content": _assistant_content(turn)})

            observations: list[dict[str, Any]] = []
            results: list[dict[str, Any]] = []
            terminal = False
            for call in turn.tool_calls:
                result = tools.execute(call.name, call.arguments, session)
                observations.append(
                    {
                        "source_call_id": call.tool_call_id,
                        "content": result.content,
                        "is_error": result.is_error,
                    }
                )
                results.append(_tool_result_block(call, result))
                # Checked against the tool name rather than the returned payload,
                # so control flow does not depend on what a tool body chose to
                # return. A failed terminal call still ends the run: the model
                # tried to hand over, and the handover is what the run was.
                terminal = terminal or call.name in tools.TERMINAL_TOOLS

            builder.add_system_step(observations)
            messages.append({"role": "user", "content": results})

            if terminal:
                final_output = turn.text
                stop_reason = "escalated"
                break
            continue

        if turn.stop_reason == "pause_turn":
            # The model paused a long turn and expects the conversation resent
            # unchanged. No step is recorded and nothing is appended to
            # ``messages``: an agent step here would be served back as a complete
            # turn on replay, and the loop would treat it as terminal. The step
            # cap is what bounds this.
            continue

        builder.add_agent_step(turn.text)
        final_output = turn.text
        stop_reason = turn.stop_reason
        break
    else:
        # The cap was hit. The trace is still written: a run that spent every turn
        # getting nowhere is evidence, and throwing it away would hide it.
        final_output = _last_agent_message(builder)
        stop_reason = "max_steps"

    return builder.build(final_output, stop_reason)


def _assistant_content(turn: ModelTurn) -> list[dict[str, Any]]:
    """Rebuild an assistant turn as content blocks for the next request.

    Rebuilt from :class:`~support_agent.model.ModelTurn` rather than kept as the
    SDK's own objects, because a replayed turn never had SDK objects. Both modes
    therefore assemble the conversation the same way.
    """
    blocks: list[dict[str, Any]] = []
    if turn.text:
        blocks.append({"type": "text", "text": turn.text})
    for call in turn.tool_calls:
        blocks.append(
            {
                "type": "tool_use",
                # The provider's own id when there is one. Replay has none and
                # never sends this array anyway, so the deterministic trace id
                # stands in and keeps the block well-formed.
                "id": call.provider_id or call.tool_call_id,
                "name": call.name,
                "input": call.arguments,
            }
        )
    return blocks


def _tool_result_block(call: Any, result: tools.ToolResult) -> dict[str, Any]:
    """One ``tool_result`` block, with the tool's payload as JSON text."""
    return {
        "type": "tool_result",
        "tool_use_id": call.provider_id or call.tool_call_id,
        "content": json.dumps(result.content, ensure_ascii=False),
        "is_error": result.is_error,
    }


def _last_agent_message(builder: trace.TraceBuilder) -> str:
    for step in reversed(builder.steps):
        if step.get("source") == "agent":
            return str(step.get("message", ""))
    return ""
