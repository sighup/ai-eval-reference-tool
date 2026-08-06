"""The provider contract, and the live implementation of it.

The agent loop never touches the Anthropic SDK. It asks a provider for the next
turn and gets a :class:`ModelTurn` — the same frozen dataclass whether the turn
came from the API or from a recorded trace. That is what lets replay exercise the
real message-assembly and tool-dispatch code instead of a parallel fake of it,
and it is why a scorer written against a replayed trace is scoring the same
pipeline that runs live.

Two decisions here are load-bearing for the trace contract:

**Tool-call ids are renumbered.** The API returns ids like
``toolu_01A9tsvL3Bp2``, which are random per call. Putting those on the trace
would mean two identical runs never diff clean, so the trace gets ``tc-1``,
``tc-2``, … and the provider id is kept in memory only long enough to build the
matching ``tool_result`` block.

**Extended thinking is switched off explicitly.** Claude Sonnet 5 turns adaptive
thinking on when ``thinking`` is omitted, and thinking blocks then have to be
preserved verbatim in the assistant turns of a tool-use conversation. The trace
has no field for thinking content, so recording it would be a schema change and
dropping it would make the replayed conversation diverge from the live one. It is
disabled instead. The cost is that the model is less eager to call tools without
being told when to, which ``prompts/system.md`` handles directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from . import config

#: Model stop reasons the loop treats as "keep going" rather than terminal.
#: ``tool_use`` means dispatch the calls and go round again; ``pause_turn`` means
#: the model paused a long turn and expects the conversation resent unchanged.
CONTINUE_REASONS = frozenset({"tool_use", "pause_turn"})

#: Sent on every request and recorded in the trace's ``params``. See the module
#: docstring for why this is explicit rather than left to the default.
THINKING_DISABLED = {"type": "disabled"}


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation.

    ``tool_call_id`` is ours and deterministic, and is what reaches the trace.
    ``provider_id`` is the API's, and never leaves this process.
    """

    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    provider_id: str | None = None

    def to_trace(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def to_trace(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
        }


@dataclass(frozen=True)
class ModelTurn:
    """One assistant turn, normalised away from the SDK's block structure."""

    text: str
    stop_reason: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class Provider(Protocol):
    """What ``agent.py`` requires. Implemented by LiveProvider and ReplayProvider.

    ``model`` and ``params`` are read by the loop and written to the trace, so the
    trace says what was actually asked for rather than what the CLI was told to
    ask for. In replay they come from the recording, which is why replaying a
    recording reproduces its configuration rather than the current defaults.
    """

    mode: str
    model: str

    @property
    def params(self) -> dict[str, Any]: ...

    def next_turn(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn: ...


class ToolCallNumberer:
    """Hands out ``tc-1``, ``tc-2``, … for the lifetime of one run."""

    def __init__(self) -> None:
        self._next = 1

    def take(self) -> str:
        value = f"tc-{self._next}"
        self._next += 1
        return value


class LiveProvider:
    """Calls the Messages API. The only thing in this package that uses network.

    The client is constructed lazily on the first turn, so importing this module
    — or constructing the provider and never using it — cannot fail for want of a
    credential, and cannot bill.
    """

    mode = "live"

    def __init__(
        self,
        model: str = config.DEFAULT_MODEL,
        max_tokens: int = config.MAX_TOKENS,
        temperature: float = config.TEMPERATURE,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client: Any | None = None
        self._numberer = ToolCallNumberer()

    @property
    def params(self) -> dict[str, Any]:
        """The request parameters that reach the trace, in schema key order.

        Built here rather than in the loop so there is one place where "what was
        sent" is defined, and no way for the trace to claim a temperature the
        request did not carry.
        """
        return {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "thinking": dict(THINKING_DISABLED),
        }

    def _get_client(self) -> Any:
        if self._client is None:
            # Imported here, not at module scope: replay must be able to run in an
            # environment where the SDK is importable but unusable, and the import
            # is the clearest marker of where the network boundary begins.
            import anthropic

            self._client = anthropic.Anthropic(api_key=config.api_key())
        return self._client

    def next_turn(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        response = self._get_client().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=messages,
            tools=tools,
            # See the module docstring: adaptive thinking is the default on
            # Sonnet 5 and the trace has nowhere to put thinking blocks.
            thinking=dict(THINKING_DISABLED),
        )
        return self.adapt(response)

    def adapt(self, response: Any) -> ModelTurn:
        """Turn an SDK ``Message`` into a :class:`ModelTurn`.

        Split out from :meth:`next_turn` so it is testable offline against real
        ``anthropic.types.Message`` objects built with ``model_validate``. That is
        what keeps the live path honest while it is developed with no key: the
        turn shape is checked against the SDK's own models rather than guessed.
        """
        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            kind = getattr(block, "type", None)
            if kind == "text":
                texts.append(block.text)
            elif kind == "tool_use":
                calls.append(
                    ToolCall(
                        tool_call_id=self._numberer.take(),
                        name=block.name,
                        arguments=dict(block.input or {}),
                        provider_id=block.id,
                    )
                )
            # Any other block type (thinking, redacted_thinking, server tool
            # blocks) is ignored rather than crashed on. The SDK pin is what keeps
            # a new block type from arriving unannounced; this keeps an
            # unrecognised one from being mistaken for the model's answer.

        usage = getattr(response, "usage", None)
        return ModelTurn(
            text="\n\n".join(t for t in texts if t).strip(),
            stop_reason=response.stop_reason or "end_turn",
            tool_calls=tuple(calls),
            usage=adapt_usage(usage),
        )


def adapt_usage(usage: Any) -> Usage:
    """Map SDK usage onto the three fields the trace records.

    ``cache_read_input_tokens`` becomes ``cached_tokens``. Cache *creation* is
    deliberately not recorded: it bills at a different rate and is an artefact of
    when a run happened rather than of what the run did, so it would make two
    otherwise identical traces disagree.
    """
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cached_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )
