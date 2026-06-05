"""Mouse and keyboard control via pyautogui.

pyautogui needs an X display. We import it lazily inside a helper and wrap every
call so a missing display (or missing Xlib) yields a clear error instead of
crashing the MCP server.

Failsafe: moving the real mouse to the very top-left corner aborts an action.
"""

from __future__ import annotations

import os

from mcp_server.tools.permissions import permission_gate
from dashboard.websocket_manager import emit_tool_call

_configured = False


def _pyautogui():
    """Import + configure pyautogui, or raise a clear RuntimeError."""
    if not os.environ.get("DISPLAY"):
        raise RuntimeError(
            "no DISPLAY is set - GUI input requires an X display. "
            "Set DISPLAY (e.g. ':0' or ':1') in the MCP server env."
        )
    try:
        import pyautogui
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"pyautogui could not be imported ({exc}). On Linux it needs an X "
            "display and python3-xlib."
        )

    global _configured
    if not _configured:
        pyautogui.FAILSAFE = True  # mouse to top-left corner aborts
        pyautogui.PAUSE = 0.1  # small delay between actions for stability
        _configured = True
    return pyautogui


def register(mcp) -> None:
    @mcp.tool()
    def move_mouse(x: int, y: int) -> str:
        """Move the mouse cursor to absolute screen coordinates (x, y)."""
        try:
            pg = _pyautogui()
            pg.moveTo(x, y)
            return emit_tool_call("move_mouse", {"x": x, "y": y}, f"Mouse moved to ({x}, {y})")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("move_mouse", {"x": x, "y": y}, f"ERROR: {exc}")

    @mcp.tool()
    def click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
        """Click at absolute coordinates (x, y).

        button: "left" | "right" | "middle". clicks: 1 for single, 2 for double.
        Requires the 'mouse_click' permission.
        """
        params = {"x": x, "y": y, "button": button, "clicks": clicks}
        denied = permission_gate("mouse_click")
        if denied:
            return emit_tool_call("click", params, denied)
        try:
            pg = _pyautogui()
            if button not in ("left", "right", "middle"):
                button = "left"
            pg.click(x=x, y=y, clicks=clicks, button=button)
            return emit_tool_call(
                "click", params, f"Clicked {button} at ({x}, {y})"
            )
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("click", params, f"ERROR: {exc}")

    @mcp.tool()
    def type_text(text: str, interval: float = 0.05) -> str:
        """Type the given text at the current focus using the keyboard.

        interval: delay between keystrokes in seconds. Requires the
        'keyboard_type' permission.
        """
        params = {"text": text, "interval": interval}
        denied = permission_gate("keyboard_type")
        if denied:
            return emit_tool_call("type_text", params, denied)
        try:
            pg = _pyautogui()
            pg.typewrite(text, interval=interval)
            return emit_tool_call("type_text", params, f"Typed: {text}")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("type_text", params, f"ERROR: {exc}")

    @mcp.tool()
    def press_key(key: str) -> str:
        """Press a single key or a combo (e.g. "enter", "ctrl+c", "alt+tab").

        "+"-separated combos are sent as a hotkey chord.
        """
        try:
            pg = _pyautogui()
            if "+" in key:
                keys = [k.strip().lower() for k in key.split("+") if k.strip()]
                pg.hotkey(*keys)
            else:
                pg.press(key.strip().lower())
            return emit_tool_call("press_key", {"key": key}, f"Pressed: {key}")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("press_key", {"key": key}, f"ERROR: {exc}")

    @mcp.tool()
    def scroll(x: int, y: int, direction: str = "down", amount: int = 3) -> str:
        """Scroll at coordinates (x, y). direction: "up" | "down".

        amount is the number of scroll "clicks".
        """
        params = {"x": x, "y": y, "direction": direction, "amount": amount}
        try:
            pg = _pyautogui()
            clicks = abs(amount) * 100
            if direction.lower() == "down":
                clicks = -clicks
            pg.scroll(clicks, x=x, y=y)
            return emit_tool_call(
                "scroll", params, f"Scrolled {direction} at ({x}, {y})"
            )
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("scroll", params, f"ERROR: {exc}")

    @mcp.tool()
    def drag(
        from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.5
    ) -> str:
        """Click-and-drag from (from_x, from_y) to (to_x, to_y).

        duration: seconds the drag takes. Requires the 'mouse_click' permission.
        """
        params = {
            "from_x": from_x,
            "from_y": from_y,
            "to_x": to_x,
            "to_y": to_y,
            "duration": duration,
        }
        denied = permission_gate("mouse_click")
        if denied:
            return emit_tool_call("drag", params, denied)
        try:
            pg = _pyautogui()
            pg.moveTo(from_x, from_y)
            pg.dragTo(to_x, to_y, duration=duration, button="left")
            return emit_tool_call(
                "drag",
                params,
                f"Dragged from ({from_x}, {from_y}) to ({to_x}, {to_y})",
            )
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("drag", params, f"ERROR: {exc}")
