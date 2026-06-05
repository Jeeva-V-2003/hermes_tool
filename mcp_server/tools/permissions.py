"""Auto-allow permission manager.

A small allowlist stored at ``~/.hermesvision/allowed_actions.json`` decides
whether sensitive tools (file writes, clicks, shell commands, ...) may run.

The file is a flat dict: ``{"action_type": true/false, ...}``.

Other tool modules import :func:`permission_gate` and call it at the very start
of any sensitive tool; if it returns a string, that string is the error the tool
must return immediately.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from mcp_server.config import (
    ACTION_TYPES,
    ALLOWED_ACTIONS_PATH,
    DEFAULT_PERMISSIONS,
    ensure_dirs,
)
from dashboard.websocket_manager import emit_permission_request, emit_tool_call


# --------------------------------------------------------------------------- #
# Allowlist persistence
# --------------------------------------------------------------------------- #


def load_permissions() -> dict[str, bool]:
    """Load the allowlist, creating it with defaults on first use."""
    ensure_dirs()
    if not os.path.exists(ALLOWED_ACTIONS_PATH):
        save_permissions(dict(DEFAULT_PERMISSIONS))
        return dict(DEFAULT_PERMISSIONS)
    try:
        with open(ALLOWED_ACTIONS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("allowlist is not an object")
        # Ensure every known action has an entry.
        changed = False
        for action in ACTION_TYPES:
            if action not in data:
                data[action] = DEFAULT_PERMISSIONS.get(action, False)
                changed = True
        if changed:
            save_permissions(data)
        return data
    except Exception:
        # Corrupt file -> reset to defaults.
        save_permissions(dict(DEFAULT_PERMISSIONS))
        return dict(DEFAULT_PERMISSIONS)


def save_permissions(perms: dict[str, bool]) -> None:
    ensure_dirs()
    with open(ALLOWED_ACTIONS_PATH, "w", encoding="utf-8") as fh:
        json.dump(perms, fh, indent=2)


def is_allowed(action_type: str) -> Optional[bool]:
    """Return True (allowed), False (denied), or None (unknown / unlisted)."""
    return load_permissions().get(action_type)


def permission_gate(action_type: str) -> Optional[str]:
    """Gate a sensitive action.

    Returns ``None`` when the action is allowed (caller proceeds), otherwise a
    ready-to-return error string. Unknown actions also raise a dashboard
    ``permission_request`` event so the user can react.
    """
    state = is_allowed(action_type)
    if state is True:
        return None
    if state is None:
        emit_permission_request(action_type)
    return (
        f"ERROR: Permission denied for {action_type}. "
        f"Use grant_permission tool to allow."
    )


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


def register(mcp) -> None:
    @mcp.tool()
    def check_permission(action_type: str) -> str:
        """Check whether an action type is currently allowed.

        Returns "ALLOWED", "DENIED", or "UNKNOWN - needs user approval".
        action_type is one of: mouse_click, keyboard_type, file_write,
        file_delete, run_command, launch_app, browser_navigate.
        """
        state = is_allowed(action_type)
        if state is True:
            result = "ALLOWED"
        elif state is False:
            result = "DENIED"
        else:
            result = "UNKNOWN - needs user approval"
        return emit_tool_call("check_permission", {"action_type": action_type}, result)

    @mcp.tool()
    def grant_permission(action_type: str) -> str:
        """Grant (allow) an action type. Persists to the allowlist file.

        action_type is one of: mouse_click, keyboard_type, file_write,
        file_delete, run_command, launch_app, browser_navigate.
        """
        perms = load_permissions()
        perms[action_type] = True
        save_permissions(perms)
        return emit_tool_call(
            "grant_permission", {"action_type": action_type}, f"Granted: {action_type}"
        )

    @mcp.tool()
    def revoke_permission(action_type: str) -> str:
        """Revoke (deny) an action type. Persists to the allowlist file.

        action_type is one of: mouse_click, keyboard_type, file_write,
        file_delete, run_command, launch_app, browser_navigate.
        """
        perms = load_permissions()
        perms[action_type] = False
        save_permissions(perms)
        return emit_tool_call(
            "revoke_permission", {"action_type": action_type}, f"Revoked: {action_type}"
        )

    @mcp.tool()
    def list_permissions() -> str:
        """List the current permission allowlist as a formatted string."""
        perms = load_permissions()
        lines = ["Current HermesVision permissions:"]
        for action in ACTION_TYPES:
            mark = "ALLOWED" if perms.get(action) else "DENIED"
            lines.append(f"  {action:<18} {mark}")
        result = "\n".join(lines)
        return emit_tool_call("list_permissions", {}, result)
