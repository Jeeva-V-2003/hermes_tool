"""Cross-process event + state bus for HermesVision.

The MCP server and the dashboard run as **separate processes**, so they cannot
share Python objects. They communicate through two files on disk:

    * EVENTS_PATH (``/tmp/hermesvision_events.jsonl``)
        Append-only JSON-lines stream. The MCP tools append events
        (``tool_called``, ``permission_request``). The dashboard tails this file
        and forwards new lines to connected WebSocket clients.

    * STATE_PATH (``/tmp/hermesvision_state.json``)
        A single JSON object holding the latest screenshot (base64) and some
        system info (last tool called, screen size, ...). The dashboard reads
        this for the live screen feed and the system-info panel.

This module is **standard library only** so it is cheap to import from the MCP
tools (no FastAPI / uvicorn pulled in).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

# Importable because both entry points insert the project root onto sys.path.
from mcp_server.config import EVENTS_PATH, STATE_PATH

# Cap how much of a tool result we store in an event so the log stays readable
# and a giant base64 blob never lands in the event stream.
_MAX_RESULT_LEN = 600


# --------------------------------------------------------------------------- #
# Events (append-only JSON lines)
# --------------------------------------------------------------------------- #


def append_event(event: dict[str, Any]) -> None:
    """Append a single event (as one JSON line) to the events file.

    Never raises - a logging failure must not break a tool call.
    """
    event.setdefault("ts", time.time())
    try:
        with open(EVENTS_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass


def _shorten(value: Any) -> str:
    text = value if isinstance(value, str) else str(value)
    if len(text) > _MAX_RESULT_LEN:
        return text[:_MAX_RESULT_LEN] + f"... [+{len(text) - _MAX_RESULT_LEN} chars]"
    return text


def emit_tool_call(tool: str, params: dict[str, Any], result: Any) -> Any:
    """Record a ``tool_called`` event and update last-tool state.

    Returns ``result`` unchanged so call sites can write::

        return emit_tool_call("click", {"x": x, "y": y}, "Clicked ...")
    """
    short = _shorten(result)
    is_error = isinstance(short, str) and short.startswith("ERROR:")
    append_event(
        {
            "type": "tool_called",
            "tool": tool,
            "params": params,
            "result": short,
            "error": is_error,
        }
    )
    try:
        update_state(last_tool=tool, last_tool_ts=time.time(), last_tool_error=is_error)
    except Exception:
        pass
    return result


def emit_permission_request(action_type: str) -> None:
    """Record a ``permission_request`` event (an UNKNOWN permission was hit)."""
    append_event({"type": "permission_request", "action_type": action_type})


def tail_events(offset: int) -> tuple[list[dict[str, Any]], int]:
    """Read new events appended since byte ``offset``.

    Returns ``(events, new_offset)``. If the file was truncated/rotated (current
    size < offset), it is re-read from the beginning.
    """
    try:
        size = os.path.getsize(EVENTS_PATH)
    except OSError:
        return [], offset

    if size < offset:  # file was reset
        offset = 0
    if size == offset:
        return [], offset

    events: list[dict[str, Any]] = []
    try:
        with open(EVENTS_PATH, "r", encoding="utf-8") as fh:
            fh.seek(offset)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            new_offset = fh.tell()
    except Exception:
        return [], offset

    return events, new_offset


def read_recent_events(limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent ``limit`` events (for initial dashboard load)."""
    try:
        with open(EVENTS_PATH, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# --------------------------------------------------------------------------- #
# State (single JSON object)
# --------------------------------------------------------------------------- #


def read_state() -> dict[str, Any]:
    """Return the current shared state object (``{}`` if missing/corrupt)."""
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_state(state: dict[str, Any]) -> None:
    """Atomically write the state object."""
    tmp = STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass


def update_state(**fields: Any) -> None:
    """Merge ``fields`` into the shared state object."""
    state = read_state()
    state.update(fields)
    _write_state(state)


def write_screen_b64(b64: str) -> None:
    """Store the latest screenshot (base64 PNG, no data: prefix) for the feed."""
    update_state(screen=b64, screen_ts=time.time())


def get_event_file_size() -> int:
    """Current byte size of the events file (0 if absent)."""
    try:
        return os.path.getsize(EVENTS_PATH)
    except OSError:
        return 0
