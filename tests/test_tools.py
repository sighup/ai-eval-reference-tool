"""Tool dispatch, argument validation, and the side-effect files.

What is under test is the dispatch mechanism: that the schemas are the shape the
Messages API accepts, that everything the model controls comes back as data rather
than an exception, and that the ledger and queue land where they are supposed to.

What each tool decides to *allow* is a property of this particular agent rather
than of the mechanism, and is not asserted here.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from support_agent import config, tools

SESSION = tools.Session(run_id="tools-01", customer_id="cust-1042", session_id="sess-0088")


@pytest.fixture(autouse=True)
def fresh_run_dir() -> None:
    tools.reset_run_dir(SESSION.run_id)


def test_the_schemas_are_shaped_the_way_the_messages_api_wants() -> None:
    for schema in tools.TOOL_SCHEMAS:
        assert set(schema) == {"name", "description", "input_schema"}
        assert schema["input_schema"]["type"] == "object"
        assert schema["input_schema"]["additionalProperties"] is False
        assert schema["description"].strip()
        # The description is the only thing the model sees.
        for spec in schema["input_schema"]["properties"].values():
            assert spec.get("description", "").strip()

    assert set(tools.TOOL_NAMES) == set(tools._HANDLERS)
    assert tools.TERMINAL_TOOLS <= set(tools.TOOL_NAMES)


@pytest.mark.parametrize(
    "name, arguments, code",
    [
        ("lookup_order", {}, "invalid_arguments"),
        ("lookup_order", {"order_id": "A-3391", "surprise": 1}, "invalid_arguments"),
        ("lookup_order", {"order_id": "Z-0000"}, "order_not_found"),
        (
            "issue_refund",
            {"order_id": "A-3391", "amount_cents": 0, "reason": "r"},
            "invalid_amount",
        ),
        ("escalate_to_human", {"reason": "r", "summary": "s"}, "invalid_arguments"),
        ("delete_all_customers", {}, "unknown_tool"),
    ],
)
def test_everything_the_model_controls_comes_back_as_data(name, arguments, code) -> None:
    """Never raised. The model needs to see a failure to recover from it, and the
    trace records it with ``is_error`` so a failed call can be told apart from a
    successful call that returned bad news."""
    result = tools.execute(name, arguments, SESSION)

    assert result.is_error
    assert result.content["error"] == code
    assert result.content["message"]


def test_a_successful_lookup_returns_serialisable_order_detail() -> None:
    """Pins order_id, placed_at, and total_cents — the values starter traces and
    examples quote — and that the payload serialises for ``tool_result`` / trace
    observation. Other payload fields are not pinned here."""
    result = tools.execute("lookup_order", {"order_id": "A-3391"}, SESSION)

    assert not result.is_error
    assert result.content["order_id"] == "A-3391"
    assert result.content["placed_at"] == "2026-05-02"
    assert result.content["total_cents"] == 4999
    assert json.loads(json.dumps(result.content)) == result.content


def test_side_effects_are_local_files_under_the_run_directory() -> None:
    tools.execute(
        "issue_refund", {"order_id": "A-3391", "amount_cents": 4999, "reason": "damaged"}, SESSION
    )
    tools.execute(
        "escalate_to_human", {"reason": "warranty", "summary": "seam", "priority": "high"}, SESSION
    )

    directory = tools.run_dir(SESSION.run_id)
    assert directory.parent == config.runs_dir()
    assert sorted(p.name for p in directory.iterdir()) == sorted(
        [tools.REFUND_LEDGER, tools.ESCALATION_QUEUE]
    )

    # The ledger records who asked *and* who owns the order, so it answers the
    # question on its own without the trace beside it.
    (refund,) = tools.read_ledger(SESSION.run_id)
    assert refund["session_customer_id"] == "cust-1042"
    assert refund["order_customer_id"] == "cust-1042"
    assert refund["amount_cents"] == 4999

    (escalation,) = tools.read_ledger(SESSION.run_id, tools.ESCALATION_QUEUE)
    assert escalation["priority"] == "high"


def test_resetting_a_run_directory_clears_prior_side_effects() -> None:
    """A ledger has to describe exactly one run, or "what did this run do?" stops
    being answerable from the files it left behind."""
    tools.execute("issue_refund", {"order_id": "A-3391", "amount_cents": 1, "reason": "r"}, SESSION)
    tools.reset_run_dir(SESSION.run_id)

    assert tools.read_ledger(SESSION.run_id) == []
    assert tools.read_ledger("a-run-that-never-happened") == []


def test_the_committed_data_matches_the_pinned_as_of_date() -> None:
    """``data/`` is a hand-maintained blob, and these are the dates the fixtures
    are written against.

    Nothing derives the data from ``AS_OF_DATE`` any more, so nothing but this
    test stops the two drifting apart. Bumping ``AS_OF_DATE`` moves the agent's
    notion of today without moving a single ``placed_at``, which silently changes
    what every fixture is asking about: A-3391 is the refund-outside-window case
    only because it is 87 days old, and B-5527 is "delayed but not lost" only
    because it is 4 days past its estimate. Both are relationships between the
    data and the clock, so neither is visible in either one alone.

    If this fails, the fix is to edit the dates in ``data/orders.json`` to
    restore the offsets — and then to re-record ``traces/starter/``, because the
    recorded answers quote the old ones.
    """
    as_of = date.fromisoformat(config.AS_OF_DATE)

    def days_ago(value: str) -> int:
        return (as_of - date.fromisoformat(value)).days

    orders = tools.orders()

    # The offsets the five starter fixtures turn on.
    assert days_ago(orders["A-3391"]["placed_at"]) == 87, "refund-outside-window"
    assert days_ago(orders["A-3402"]["placed_at"]) == 40, "final sale, inside the window"
    assert days_ago(orders["B-5510"]["placed_at"]) == 12, "refund-in-window"
    assert days_ago(orders["B-5527"]["placed_at"]) == 11, "order-status"
    assert days_ago(orders["C-7744"]["placed_at"]) == 150, "escalation-request"
    assert days_ago(orders["C-7781"]["placed_at"]) == 2, "still cancellable"

    # B-5527 is the delayed-shipment case, which is the gap between its estimate
    # and today rather than anything about the order on its own.
    assert days_ago(orders["B-5527"]["shipping"]["estimated_delivery"]) == 4

    # Quoted in the spec's worked example, and in the frozen traces' prose.
    assert orders["A-3391"]["placed_at"] == "2026-05-02"
    assert orders["A-3391"]["total_cents"] == 4999


def test_every_order_is_owned_by_a_customer_that_exists() -> None:
    """``lookup_order`` reads the owning customer's name and address straight out
    of ``customers.json``. A dangling ``customer_id`` would not raise — it would
    return a null name to the model, which is a worse failure than an error."""
    customers = tools.customers()
    dangling = {
        order_id: order["customer_id"]
        for order_id, order in tools.orders().items()
        if order["customer_id"] not in customers
    }

    assert not dangling, f"orders reference customers that do not exist: {dangling}"
