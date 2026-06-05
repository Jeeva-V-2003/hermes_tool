#!/usr/bin/env python3
"""HermesVision dashboard - FastAPI web app on port 7860.

Runs as a SEPARATE process from the MCP server. It never imports the GUI/browser
tools; it only reads the shared state + events files that the MCP server writes,
and streams them to the browser over a WebSocket.
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import time

# Make the project root importable when run as `python dashboard/app.py`.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from mcp_server.config import (  # noqa: E402
    ACTION_TYPES,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    get_screen_size,
)
from mcp_server.tools.permissions import load_permissions, save_permissions  # noqa: E402
from dashboard import websocket_manager as bus  # noqa: E402

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_START_TIME = time.time()

app = FastAPI(title="HermesVision Dashboard")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


def _sysinfo() -> dict:
    width, height = get_screen_size()
    state = bus.read_state()
    return {
        "screen_width": width,
        "screen_height": height,
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "uptime_seconds": int(time.time() - _START_TIME),
        "last_tool": state.get("last_tool"),
        "last_tool_ts": state.get("last_tool_ts"),
        "display": os.environ.get("DISPLAY", "(unset)"),
    }


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/api/screen")
def api_screen() -> JSONResponse:
    state = bus.read_state()
    return JSONResponse({"image": state.get("screen", ""), "ts": state.get("screen_ts")})


@app.get("/api/perms")
def api_perms() -> JSONResponse:
    return JSONResponse(load_permissions())


@app.get("/api/sysinfo")
def api_sysinfo() -> JSONResponse:
    return JSONResponse(_sysinfo())


def _set_perm(action_type: str, value: bool) -> JSONResponse:
    if action_type not in ACTION_TYPES:
        return JSONResponse(
            {"error": f"unknown action_type: {action_type}"}, status_code=400
        )
    perms = load_permissions()
    perms[action_type] = value
    save_permissions(perms)
    bus.append_event(
        {"type": "permission_changed", "action_type": action_type, "allowed": value}
    )
    return JSONResponse(perms)


@app.post("/api/perms/{action_type}/grant")
def api_grant(action_type: str) -> JSONResponse:
    return _set_perm(action_type, True)


@app.post("/api/perms/{action_type}/revoke")
def api_revoke(action_type: str) -> JSONResponse:
    return _set_perm(action_type, False)


# --------------------------------------------------------------------------- #
# WebSocket: live events + screen feed
# --------------------------------------------------------------------------- #


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()

    # Initial snapshot for a freshly connected client.
    state = bus.read_state()
    await ws.send_json(
        {
            "type": "init",
            "events": bus.read_recent_events(50),
            "perms": load_permissions(),
            "screen": state.get("screen", ""),
            "sysinfo": _sysinfo(),
        }
    )

    # Stream new events (poll every 500ms) and the screen (every ~2s).
    offset = bus.get_event_file_size()
    tick = 0
    try:
        while True:
            events, offset = bus.tail_events(offset)
            for event in events:
                await ws.send_json(event)

            tick += 1
            if tick % 4 == 0:  # ~ every 2 seconds
                state = bus.read_state()
                screen = state.get("screen", "")
                if screen:
                    await ws.send_json({"type": "screen_update", "image": screen})
                await ws.send_json({"type": "sysinfo", "sysinfo": _sysinfo()})

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    except Exception:
        # Any send failure -> client is gone; just end the coroutine.
        return


def main() -> None:
    import uvicorn

    print(f"HermesVision dashboard -> http://localhost:{DASHBOARD_PORT}", flush=True)
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT, log_level="warning")


if __name__ == "__main__":
    main()
