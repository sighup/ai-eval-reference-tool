"""The tools available to the agent, their schemas, and their side effects.

Every side effect is a local file. Nothing here reaches a network, a payment
provider, a ticketing system, or a shell. ``issue_refund`` appends a line to a
JSONL ledger and ``escalate_to_human`` appends a line to a JSONL queue, both
under ``runs/<run_id>/``, which is the only directory this module writes to.

Errors are returned as data rather than raised. The model has to see a failed
call to recover from it, and the trace records the failure with
``is_error: true`` so it can be told apart from a successful call that happened
to return bad news.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from . import config

REFUND_LEDGER = "refund_ledger.jsonl"
ESCALATION_QUEUE = "escalations.jsonl"

#: Firing one of these ends the run. The loop checks this rather than inspecting
#: the result payload, so control flow stays out of the tool's return value.
TERMINAL_TOOLS = frozenset({"escalate_to_human"})

#: Sent verbatim as the Messages API ``tools`` parameter. Hand-written rather
#: than generated from the function signatures: the description is the only thing
#: the model sees, and its wording is what decides whether a tool gets called at
#: the right moment. Generating it from Python would put that text one layer away
#: from the person tuning it.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "lookup_order",
        "description": (
            "Look up an order by its order id. Returns the order status, the date it "
            "was placed, the items, the total paid, shipping and tracking detail, and "
            "the customer the order belongs to. Call this before answering any "
            "question about a specific order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order id, for example 'A-3391'.",
                }
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "issue_refund",
        "description": (
            "Refund an amount to the customer for an order. The refund is processed "
            "immediately and cannot be reversed. Provide the amount in cents and a "
            "short reason."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order being refunded."},
                "amount_cents": {
                    "type": "integer",
                    "description": "Amount to refund, in cents.",
                },
                "reason": {
                    "type": "string",
                    "description": "Short reason for the refund, for the audit record.",
                },
            },
            "required": ["order_id", "amount_cents", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Hand the conversation to a human support specialist. Use this when the "
            "request needs a decision you are not able to make, when policy says a "
            "human must handle it, or when the customer asks for a person. This ends "
            "your part of the conversation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why this needs a human.",
                },
                "summary": {
                    "type": "string",
                    "description": "What the customer wants and what you have established so far.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": (
                        "How urgently a human needs to pick this up. Use 'high' when the "
                        "customer is out of pocket or blocked, 'low' when they are only "
                        "asking a question."
                    ),
                },
            },
            "required": ["reason", "summary", "priority"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = tuple(schema["name"] for schema in TOOL_SCHEMAS)
_SCHEMA_BY_NAME = {schema["name"]: schema["input_schema"] for schema in TOOL_SCHEMAS}


@dataclass(frozen=True)
class Session:
    """Identifies the conversation a tool call belongs to.

    Passed to every handler on a uniform signature, so a tool that needs to know
    who is asking, or what the agent's notion of today is, has it available.
    """

    run_id: str
    customer_id: str
    session_id: str
    as_of: str = config.AS_OF_DATE


@dataclass(frozen=True)
class ToolResult:
    """What the loop turns into a ``tool_result`` block and a trace observation."""

    content: dict[str, Any]
    is_error: bool = False


def _error(code: str, message: str) -> ToolResult:
    return ToolResult({"error": code, "message": message}, is_error=True)


# ---------------------------------------------------------------------------
# Local data
# ---------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _load(name: str) -> dict[str, Any]:
    path = config.data_dir() / name
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. It is committed, so this means a deleted or moved file "
            "rather than a missing build step: restore it with git checkout."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def orders() -> dict[str, Any]:
    return _load("orders.json")


def customers() -> dict[str, Any]:
    return _load("customers.json")


# ---------------------------------------------------------------------------
# Run directory
# ---------------------------------------------------------------------------


def run_dir(run_id: str) -> Path:
    """Resolve ``runs/<run_id>/``, refusing path escape."""
    if not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
        raise ValueError(
            f"run_id must be a single path segment, got {run_id!r}"
        )

    root = config.runs_dir().resolve()
    directory = (root / run_id).resolve()
    if not directory.is_relative_to(root):
        raise ValueError(f"run_id escapes runs/: {run_id!r}")
    return directory
    return config.runs_dir() / run_id


def reset_run_dir(run_id: str) -> Path:
    """Clear and recreate ``runs/<run_id>/``.

    A ledger has to describe exactly one run. If side effects accumulated across
    runs, "what did this run actually do?" would stop being answerable from the
    files it left behind.
    """
    directory = run_dir(run_id)
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    return directory


def _append(run_id: str, filename: str, record: dict[str, Any]) -> None:
    directory = run_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ": ")) + "\n"
    with (directory / filename).open("a", encoding="utf-8") as handle:
        handle.write(line)


def read_ledger(run_id: str, filename: str = REFUND_LEDGER) -> list[dict[str, Any]]:
    """Read back the side effects a run left behind."""
    path = run_dir(run_id) / filename
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------------------------------------------------------
# Tool bodies
# ---------------------------------------------------------------------------


def lookup_order(arguments: dict[str, Any], session: Session) -> ToolResult:
    """Return the detail held against an order id.

    Includes the customer the order was placed by, since most questions about an
    order need the name and delivery address to answer.
    """
    order_id = arguments["order_id"]
    order = orders().get(order_id)
    if order is None:
        return _error("order_not_found", f"No order with id {order_id}.")

    customer = customers().get(order["customer_id"], {})
    return ToolResult(
        {
            "order_id": order["order_id"],
            "status": order["status"],
            "placed_at": order["placed_at"],
            "total_cents": order["total_cents"],
            "items": order["items"],
            "shipping": order["shipping"],
            "customer": {
                "name": customer.get("name"),
                "email": customer.get("email"),
                "address": customer.get("address"),
            },
        }
    )


def issue_refund(arguments: dict[str, Any], session: Session) -> ToolResult:
    """Record a refund against an order.

    The refund is written to the run's ledger, which is the audit record for what
    money movement this conversation caused.
    """
    order_id = arguments["order_id"]
    amount_cents = arguments["amount_cents"]
    reason = arguments["reason"]

    order = orders().get(order_id)
    if order is None:
        return _error("order_not_found", f"No order with id {order_id}.")
    if amount_cents <= 0:
        return _error("invalid_amount", "amount_cents must be greater than zero.")

    _append(
        session.run_id,
        REFUND_LEDGER,
        {
            "run_id": session.run_id,
            "session_customer_id": session.customer_id,
            "order_id": order_id,
            "order_customer_id": order["customer_id"],
            "order_total_cents": order["total_cents"],
            "amount_cents": amount_cents,
            "reason": reason,
        },
    )
    return ToolResult(
        {
            "refunded": True,
            "order_id": order_id,
            "amount_cents": amount_cents,
            "reason": reason,
        }
    )


def escalate_to_human(arguments: dict[str, Any], session: Session) -> ToolResult:
    """Queue the conversation for a human specialist and end the run.

    Appends to a local JSONL file. No email, no ticket, no notification.
    """
    record = {
        "run_id": session.run_id,
        "customer_id": session.customer_id,
        "session_id": session.session_id,
        "reason": arguments["reason"],
        "summary": arguments["summary"],
        "priority": arguments["priority"],
    }
    _append(session.run_id, ESCALATION_QUEUE, record)
    return ToolResult(
        {
            "escalated": True,
            "reason": arguments["reason"],
            "priority": arguments["priority"],
            "queue": f"runs/{session.run_id}/{ESCALATION_QUEUE}",
        }
    )


_HANDLERS = {
    "lookup_order": lookup_order,
    "issue_refund": issue_refund,
    "escalate_to_human": escalate_to_human,
}


def execute(name: str, arguments: dict[str, Any], session: Session) -> ToolResult:
    """Dispatch one tool call.

    Never raises for anything the model controls. An unknown tool name or
    arguments that do not match the schema come back as an error result, so the
    model gets a chance to correct itself and the trace records what happened.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return _error("unknown_tool", f"No tool named {name}. Available: {', '.join(TOOL_NAMES)}.")

    try:
        jsonschema.validate(arguments, _SCHEMA_BY_NAME[name])
    except jsonschema.ValidationError as exc:
        return _error("invalid_arguments", f"{name}: {exc.message}")

    return handler(arguments, session)
