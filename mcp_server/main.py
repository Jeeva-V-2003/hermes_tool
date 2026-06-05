#!/usr/bin/env python3
"""HermesVision MCP server entry point (stdio transport).

Hermes spawns this file as a subprocess and speaks the Model Context Protocol
over stdin/stdout. Therefore **nothing may be written to stdout** except MCP
protocol frames - all logging goes to stderr / ~/.hermesvision/mcp_server.log.

Run standalone for a sanity check:
    .venv/bin/python mcp_server/main.py        # then Ctrl-C
"""

from __future__ import annotations

import os
import sys

# Make the project root importable whether this file is run as a script
# (`python mcp_server/main.py`) or as a module. This lets the tool modules do
# `from dashboard.websocket_manager import ...` and `from mcp_server...`.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP  # noqa: E402

from mcp_server.config import ensure_dirs, setup_logging  # noqa: E402
from mcp_server.tools import (  # noqa: E402
    api_caller,
    app_launcher,
    browser,
    filesystem,
    input_control,
    permissions,
    screen,
)

logger = setup_logging()

# FastMCP server. The name is what Hermes shows for this toolset.
mcp = FastMCP("hermesvision")

# Register every tool module onto the shared server instance.
_MODULES = [
    screen,
    input_control,
    filesystem,
    browser,
    app_launcher,
    api_caller,
    permissions,
]


_registered = False


def _register_all() -> None:
    global _registered
    if _registered:
        return
    ensure_dirs()
    for module in _MODULES:
        module.register(mcp)
        logger.info("registered tools from %s", module.__name__)
    _registered = True


def main() -> None:
    _register_all()
    logger.info("HermesVision MCP server starting (stdio transport)")
    # FastMCP.run() defaults to the stdio transport.
    mcp.run()


# Register at import time too, so the smoke-test harness can import this module
# and introspect the tool list without starting the stdio loop.
_register_all()


if __name__ == "__main__":
    main()
