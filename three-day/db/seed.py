"""Build the Northwind Goods SQLite database the three-day course runs against.

    uv run python three-day/db/seed.py

The base rows come from ``data/customers.json`` and ``data/orders.json``, the
same records the rest of the reference tool uses. On top of them this script adds
the mess a real support database has and a JSON file does not: orders that went
out in two parcels, a customer who moved, a delivery the carrier never dated,
earlier refunds, returns still in the post, order records that disagree with the
carrier, and two tool calls that fail. Each one is listed in ``MESS`` below with
the reason it is there.

The output is ``three-day/db/northwind.db``. It is the *seed*: no run writes to
it. Each run gets its own copy (see ``support_agent.sqlite_store``), so one run's
refunds can never leak into the next.

The script is deterministic. Run it twice and you get the same database.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "data"
OUT = HERE / "northwind.db"

SCHEMA = """
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    joined_at   TEXT NOT NULL
);

-- A customer's addresses over time. The current one has valid_to NULL.
CREATE TABLE addresses (
    address_id  INTEGER PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    line1       TEXT NOT NULL,
    line2       TEXT,
    city        TEXT NOT NULL,
    region      TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    country     TEXT NOT NULL,
    valid_from  TEXT NOT NULL,
    valid_to    TEXT
);

CREATE TABLE orders (
    order_id            TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers(customer_id),
    placed_at           TEXT NOT NULL,
    status              TEXT NOT NULL,
    total_cents         INTEGER NOT NULL,
    ship_to_address_id  INTEGER REFERENCES addresses(address_id),
    promised_by         TEXT
);

CREATE TABLE order_items (
    order_id         TEXT NOT NULL REFERENCES orders(order_id),
    line_no          INTEGER NOT NULL,
    sku              TEXT NOT NULL,
    name             TEXT NOT NULL,
    quantity         INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL,
    final_sale       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, line_no)
);

-- One row per parcel. Most orders have one; some have two.
CREATE TABLE shipments (
    shipment_id        TEXT PRIMARY KEY,
    order_id           TEXT NOT NULL REFERENCES orders(order_id),
    carrier            TEXT NOT NULL,
    tracking_number    TEXT NOT NULL,
    status             TEXT NOT NULL,
    estimated_delivery TEXT,
    delivered_at       TEXT,
    skus               TEXT NOT NULL
);

CREATE TABLE returns (
    return_id   TEXT PRIMARY KEY,
    order_id    TEXT NOT NULL REFERENCES orders(order_id),
    sku         TEXT NOT NULL,
    opened_at   TEXT NOT NULL,
    received_at TEXT
);

-- Money back to a customer. Rows from before the course have run_id NULL.
CREATE TABLE refunds (
    refund_id           INTEGER PRIMARY KEY,
    order_id            TEXT NOT NULL REFERENCES orders(order_id),
    amount_cents        INTEGER NOT NULL,
    method              TEXT NOT NULL,
    reason              TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    created_by          TEXT NOT NULL,
    run_id              TEXT,
    session_customer_id TEXT
);

CREATE TABLE escalations (
    escalation_id INTEGER PRIMARY KEY,
    run_id        TEXT NOT NULL,
    customer_id   TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    reason        TEXT NOT NULL,
    summary       TEXT NOT NULL,
    priority      TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

-- What happened to an order, newest last. Cancellations by the agent land here.
CREATE TABLE order_events (
    event_id   INTEGER PRIMARY KEY,
    order_id   TEXT NOT NULL REFERENCES orders(order_id),
    at         TEXT NOT NULL,
    event      TEXT NOT NULL,
    detail     TEXT,
    run_id     TEXT
);

-- Injected failures, so a run can meet a tool that does not work.
-- mode 'once' fails the first call for that order in a run; 'always' every call.
CREATE TABLE faults (
    tool     TEXT NOT NULL,
    order_id TEXT NOT NULL,
    mode     TEXT NOT NULL CHECK (mode IN ('once', 'always')),
    error    TEXT NOT NULL,
    message  TEXT NOT NULL,
    PRIMARY KEY (tool, order_id)
);

-- Every tool call a run makes. Used to decide whether a 'once' fault has fired.
CREATE TABLE tool_calls (
    call_id  INTEGER PRIMARY KEY,
    run_id   TEXT NOT NULL,
    tool     TEXT NOT NULL,
    order_id TEXT,
    ok       INTEGER NOT NULL
);
"""

#: Each change to the base data, and why a course needs it. Applied in order.
MESS: list[tuple[str, str, tuple]] = [
    # --- A customer who moved -------------------------------------------------
    (
        "cust-1042 moved on 2026-07-16. Orders before that ship to the old address.",
        "UPDATE addresses SET valid_to = '2026-07-15' WHERE customer_id = 'cust-1042'",
        (),
    ),
    (
        "",
        "INSERT INTO addresses (customer_id, line1, line2, city, region, postal_code, "
        "country, valid_from) VALUES ('cust-1042', '1290 Alder Row', 'Apt 4', "
        "'Ashfield', 'OR', '97141', 'US', '2026-07-16')",
        (),
    ),
    (
        "",
        "UPDATE orders SET ship_to_address_id = (SELECT address_id FROM addresses "
        "WHERE customer_id = 'cust-1042' AND valid_to IS NULL) "
        "WHERE customer_id = 'cust-1042' AND placed_at >= '2026-07-16'",
        (),
    ),
    # --- An order that went out in two parcels --------------------------------
    (
        "A-3286 split: cook set and mug delivered, the three rain shells still moving.",
        "UPDATE shipments SET skus = 'NG-3801,NG-1907', status = 'delivered', "
        "estimated_delivery = '2026-07-24', delivered_at = '2026-07-24' "
        "WHERE order_id = 'A-3286'",
        (),
    ),
    (
        "",
        "INSERT INTO shipments VALUES ('A-3286-2', 'A-3286', 'Cascade Parcel', "
        "'CP550913377102', 'in_transit', '2026-07-30', NULL, 'NG-3090')",
        (),
    ),
    # --- A delivery the carrier never dated -----------------------------------
    (
        "A-3452 is marked delivered, but the carrier sent no delivery date.",
        "UPDATE shipments SET delivered_at = NULL WHERE order_id = 'A-3452'",
        (),
    ),
    # --- A parcel that is lost by policy (10+ business days late) -------------
    (
        "A-3275 never arrived: due 2026-07-08, still in transit.",
        "UPDATE orders SET status = 'in_transit', promised_by = '2026-07-08' "
        "WHERE order_id = 'A-3275'",
        (),
    ),
    (
        "",
        "UPDATE shipments SET status = 'in_transit', estimated_delivery = '2026-07-08', "
        "delivered_at = NULL WHERE order_id = 'A-3275'",
        (),
    ),
    # --- The order record and the carrier disagree ----------------------------
    (
        "B-5405 says processing, but the carrier scanned a parcel for it today.",
        "INSERT INTO shipments VALUES ('B-5405-1', 'B-5405', 'Northline Freight', "
        "'NF77120394411', 'in_transit', '2026-08-04', NULL, 'NG-4410')",
        (),
    ),
    # --- Money that has already moved -----------------------------------------
    (
        "B-5417: staff already refunded the serving bowl.",
        "INSERT INTO refunds (order_id, amount_cents, method, reason, created_at, "
        "created_by) VALUES ('B-5417', 2600, 'card', 'Serving bowl returned', "
        "'2026-07-24', 'staff:rpatel')",
        (),
    ),
    (
        "B-5424: the quilt was sent back the day it arrived, and refunded yesterday.",
        "INSERT INTO returns VALUES ('R-0912', 'B-5424', 'NG-3177', '2026-07-25', "
        "'2026-07-27')",
        (),
    ),
    (
        "",
        "INSERT INTO refunds (order_id, amount_cents, method, reason, created_at, "
        "created_by) VALUES ('B-5424', 15900, 'card', 'Return received', "
        "'2026-07-27', 'system')",
        (),
    ),
    (
        "A-3468: a return label was used for the daypack, but it has not arrived.",
        "INSERT INTO returns VALUES ('R-0931', 'A-3468', 'NG-1180', '2026-07-25', NULL)",
        (),
    ),
    # --- Tools that fail -------------------------------------------------------
    (
        "Looking up A-3509 times out the first time, then works.",
        "INSERT INTO faults VALUES ('lookup_order', 'A-3509', 'once', "
        "'service_unavailable', 'The order service did not respond in time. "
        "Try again.')",
        (),
    ),
    (
        "Refunds to the card on A-3282 are declined by the payment provider.",
        "INSERT INTO faults VALUES ('issue_refund', 'A-3282', 'always', "
        "'payment_provider_error', 'The payment provider declined the refund "
        "(code PP-402). No money was moved.')",
        (),
    ),
]


def _base(db: sqlite3.Connection) -> None:
    customers = json.loads((DATA / "customers.json").read_text(encoding="utf-8"))
    orders = json.loads((DATA / "orders.json").read_text(encoding="utf-8"))

    address_of: dict[str, int] = {}
    for cust in customers.values():
        db.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?)",
            (cust["customer_id"], cust["name"], cust["email"], cust["joined_at"]),
        )
        a = cust["address"]
        cur = db.execute(
            "INSERT INTO addresses (customer_id, line1, line2, city, region, "
            "postal_code, country, valid_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cust["customer_id"],
                a["line1"],
                a["line2"],
                a["city"],
                a["region"],
                a["postal_code"],
                a["country"],
                cust["joined_at"],
            ),
        )
        address_of[cust["customer_id"]] = int(cur.lastrowid or 0)

    for order in sorted(orders.values(), key=lambda o: o["order_id"]):
        ship = order["shipping"]
        db.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                order["order_id"],
                order["customer_id"],
                order["placed_at"],
                order["status"],
                order["total_cents"],
                address_of[order["customer_id"]],
                ship["estimated_delivery"],
            ),
        )
        for line_no, item in enumerate(order["items"], start=1):
            db.execute(
                "INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    order["order_id"],
                    line_no,
                    item["sku"],
                    item["name"],
                    item["quantity"],
                    item["unit_price_cents"],
                    1 if item.get("final_sale") else 0,
                ),
            )
        if ship["carrier"]:
            db.execute(
                "INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{order['order_id']}-1",
                    order["order_id"],
                    ship["carrier"],
                    ship["tracking_number"],
                    order["status"],
                    ship["estimated_delivery"],
                    ship["delivered_at"],
                    ",".join(item["sku"] for item in order["items"]),
                ),
            )
        if order["status"] == "cancelled":
            # A cancelled order was refunded in full the day it was cancelled.
            db.execute(
                "INSERT INTO order_events (order_id, at, event, detail) "
                "VALUES (?, ?, 'cancelled', 'Cancelled by customer')",
                (order["order_id"], order["placed_at"]),
            )
            db.execute(
                "INSERT INTO refunds (order_id, amount_cents, method, reason, "
                "created_at, created_by) VALUES (?, ?, 'card', 'Order cancelled', ?, "
                "'system')",
                (order["order_id"], order["total_cents"], order["placed_at"]),
            )


def build(out: Path = OUT) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        _base(db)
        for _why, sql, params in MESS:
            db.execute(sql, params)
        db.commit()
    finally:
        db.close()
    tmp.replace(out)
    return out


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    path = build(out)
    db = sqlite3.connect(path)
    counts = {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("customers", "orders", "shipments", "refunds", "returns", "faults")
    }
    db.close()
    print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    print("  " + "  ".join(f"{name} {n}" for name, n in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
