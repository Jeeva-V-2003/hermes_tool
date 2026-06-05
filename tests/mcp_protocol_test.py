#!/usr/bin/env python3
"""Drive the HermesVision server over the real MCP stdio transport.

This is exactly how Hermes talks to it: spawn `python mcp_server/main.py`,
perform the MCP handshake, list tools, and call a few. It also proves the
server's stdout carries ONLY protocol frames (a stray print would break the
JSON-RPC stream and this test).

Run:
    .venv/bin/python tests/mcp_protocol_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def run() -> int:
    venv_py = os.path.join(_ROOT, ".venv", "bin", "python")
    params = StdioServerParameters(
        command=venv_py if os.path.exists(venv_py) else sys.executable,
        args=[os.path.join(_ROOT, "mcp_server", "main.py")],
        env={
            "DISPLAY": os.environ.get("DISPLAY", ":0"),
            "HERMESVISION_DASHBOARD_PORT": "7860",
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        },
    )

    print("Spawning MCP server over stdio (as Hermes would)…")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"  initialized: server = {init.serverInfo.name} "
                  f"v{init.serverInfo.version}")

            tools = (await session.list_tools()).tools
            print(f"  tools/list returned {len(tools)} tools")

            # Call a safe, side-effect-free tool through the protocol.
            res = await session.call_tool("list_permissions", {})
            text = res.content[0].text if res.content else ""
            ok_perms = "permissions" in text.lower()
            print(f"  tools/call list_permissions -> "
                  f"{'OK' if ok_perms else 'UNEXPECTED'}")

            # Call a tool that returns structured data.
            res2 = await session.call_tool("capture_screen", {"region": "0,0,120,120"})
            text2 = res2.content[0].text if res2.content else ""
            ok_cap = text2.startswith("data:image/png;base64,") or text2.startswith("ERROR:")
            print(f"  tools/call capture_screen -> "
                  f"{'OK' if ok_cap else 'UNEXPECTED'} ({text2[:42]}…)")

            names = {t.name for t in tools}
            expected = {"capture_screen", "click", "write_file", "browser_open",
                        "http_request", "list_permissions"}
            missing = expected - names
            if missing:
                print(f"  MISSING expected tools: {missing}")
                return 1

            if len(tools) >= 30 and ok_perms and ok_cap:
                print("\nMCP stdio transport OK — Hermes can drive HermesVision.")
                return 0
            print("\nSomething was off in the protocol exchange.")
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
