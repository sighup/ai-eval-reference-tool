"""The support agent's tools as a stdio MCP server, for recording runs through Claude Code.

You do not run this yourself. ``record.py --via claude`` starts one per run and
points ``claude -p`` at it, so the support agent can run on Claude Code's own
model access instead of an API key. The tools are the same functions the API
runner calls (``support_agent.tools.execute``) against the same per-run database.

    python three-day/lab/mcp_server.py --run-id ID --customer CUST --session SESS --as-of DATE

It speaks just enough of MCP for Claude Code: initialize, tools/list, tools/call.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SUPPORT_AGENT_BACKEND", "sqlite")

from support_agent import tools  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--customer", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()

    session = tools.Session(
        run_id=args.run_id,
        customer_id=args.customer,
        session_id=args.session,
        as_of=args.as_of,
    )
    schemas = tools.tool_schemas()

    def send(obj: dict) -> None:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            version = (msg.get("params") or {}).get("protocolVersion", "2025-06-18")
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": version,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "northwind", "version": "1"},
                    },
                }
            )
        elif method == "tools/list":
            listed = [
                {"name": s["name"], "description": s["description"], "inputSchema": s["input_schema"]}
                for s in schemas
            ]
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": listed}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            result = tools.execute(params.get("name", ""), params.get("arguments") or {}, session)
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result.content)}],
                        "isError": result.is_error,
                    },
                }
            )
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
