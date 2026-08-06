"""Paths, pinned constants, and the pricing table.

Nothing here reads the wall clock. The refund-window logic needs a stable notion
of "87 days ago", so "now" is a pinned constant that a caller can override.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

SCHEMA_VERSION = "1.0"

PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-sonnet-5"

#: The agent's notion of "today". Pinned, never ``date.today()`` — the
#: refund-outside-window fixture needs "87 days ago" to mean the same thing on
#: every machine on every day, or replaying a fixture stops being deterministic.
AS_OF_DATE = "2026-07-28"

#: Loop cap. Hitting it writes a trace with ``stop_reason: "max_steps"`` rather
#: than throwing the steps away. A run that spent eight turns getting nowhere
#: is worth having a record of.
DEFAULT_MAX_STEPS = 8

MAX_TOKENS = 2048

#: Sampling temperature. Left at the API default rather than dropped to zero.
#:
#: Zero would make repeated runs *look* stable without being reproducible — the
#: API gives no determinism guarantee at any temperature — and it would hide the
#: run-to-run variance that a single-sample measurement gets wrong. Better to see
#: the spread and account for it. Override with ``--temperature`` when you want to
#: measure how much of a change came from sampling.
TEMPERATURE = 1.0

#: Top-k documents retrieval returns per user turn.
RETRIEVAL_TOP_K = 3

#: USD per million tokens for the default model. Standard rates, not the
#: introductory promotion, so a frozen ``cost_usd`` does not silently change
#: meaning when the promotion ends. Cache reads bill at 0.1x input.
PRICE_PER_MTOK = {
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
_FALLBACK_PRICE = {"input": 3.00, "output": 15.00}

#: Floats are written at fixed precision so a frozen trace re-serialises byte
#: for byte. Without this, diffing a frozen trace against a fresh run is noise.
SCORE_PRECISION = 4
COST_PRECISION = 6


def project_root() -> Path:
    """The ``reference-tool/`` directory.

    Found by walking up from this file looking for ``pyproject.toml``, so
    ``corpus/`` and ``data/`` resolve the same way whether the package is
    imported from the source tree or from an installed copy alongside it.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError(
        f"Could not locate the project root: no pyproject.toml above {Path(__file__).resolve()}"
    )


def corpus_dir() -> Path:
    return project_root() / "corpus"


def data_dir() -> Path:
    return project_root() / "data"


def traces_dir() -> Path:
    return project_root() / "traces"


def runs_dir() -> Path:
    return project_root() / "runs"


def schema_path() -> Path:
    return project_root() / "schema" / "trace-v1.json"


def load_env() -> None:
    """Load ``reference-tool/.env`` if present.

    Loading a key does not by itself cause a call. Only :class:`LiveProvider
    <support_agent.model.LiveProvider>` reaches the network, and ``--replay``
    never constructs a client at all.
    """
    load_dotenv(project_root() / ".env")


def api_key() -> str:
    """The one credential this tool accepts. Only the live provider calls this."""
    load_env()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise MissingCredential(
            "ANTHROPIC_API_KEY is not set, so a live run cannot start.\n"
            "Copy .env.example to .env and add your key, or export the variable.\n"
            "To run without a key, replay a recording: --replay traces/starter/<file>.jsonl"
        )
    return key


def price_for(model: str) -> dict[str, float]:
    return PRICE_PER_MTOK.get(model, _FALLBACK_PRICE)


def cost_usd(model: str, input_tokens: int, output_tokens: int, cached_tokens: int) -> float:
    """Cost of one run, rounded so the trace is stable under re-serialisation."""
    price = price_for(model)
    total = (
        input_tokens * price["input"]
        + output_tokens * price["output"]
        + cached_tokens * price["input"] * 0.1
    ) / 1_000_000
    return round(total, COST_PRECISION)


class MissingCredential(RuntimeError):
    """Raised instead of a stack trace when ``--live`` has no API key."""
