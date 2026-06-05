"""Screen capture + vision tools.

Capture is done with ``mss`` (fast, works on X11). If ``mss`` fails - e.g. on
some Wayland setups - we fall back to the ``scrot`` command line tool. Every
capture is also broadcast to the dashboard live feed.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess

from mcp_server.config import SCREENSHOT_PATH, get_screen_size
from dashboard.websocket_manager import emit_tool_call, write_screen_b64


def _compute_box(region: str) -> dict[str, int]:
    """Translate a region keyword (or "x,y,w,h") into an mss bounding box."""
    width, height = get_screen_size()
    region = (region or "full").strip().lower()

    if region == "full":
        return {"left": 0, "top": 0, "width": width, "height": height}
    if region == "top-half":
        return {"left": 0, "top": 0, "width": width, "height": height // 2}
    if region == "bottom-half":
        return {"left": 0, "top": height // 2, "width": width, "height": height - height // 2}
    if region == "left-half":
        return {"left": 0, "top": 0, "width": width // 2, "height": height}
    if region == "right-half":
        return {"left": width // 2, "top": 0, "width": width - width // 2, "height": height}

    # Custom "x,y,width,height"
    parts = [p.strip() for p in region.split(",")]
    if len(parts) == 4:
        try:
            x, y, w, h = (int(float(p)) for p in parts)
            return {"left": x, "top": y, "width": w, "height": h}
        except ValueError:
            pass
    # Anything unrecognised -> full screen.
    return {"left": 0, "top": 0, "width": width, "height": height}


def _grab_png_bytes(box: dict[str, int]) -> bytes:
    """Capture ``box`` and return PNG bytes. Tries mss, falls back to scrot."""
    # --- Primary path: mss -------------------------------------------------
    try:
        import mss
        import mss.tools

        with mss.mss() as sct:
            shot = sct.grab(box)
            return mss.tools.to_png(shot.rgb, shot.size)
    except Exception:
        pass

    # --- Fallback path: scrot (captures full screen, then crop with PIL) ---
    try:
        full_path = "/tmp/hermesvision_scrot_full.png"
        subprocess.run(
            ["scrot", "--overwrite", full_path],
            check=True,
            capture_output=True,
            timeout=15,
        )
        from PIL import Image

        img = Image.open(full_path).convert("RGB")
        crop = img.crop(
            (
                box["left"],
                box["top"],
                box["left"] + box["width"],
                box["top"] + box["height"],
            )
        )
        import io

        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 - surface a clean message upstream
        raise RuntimeError(
            "screen capture failed via mss and scrot. Is a display available "
            "(DISPLAY set) and is 'scrot' installed for Wayland fallback? "
            f"Underlying error: {exc}"
        )


def _capture(region: str) -> str:
    """Capture ``region``, persist PNG + broadcast, return raw base64 (no prefix)."""
    box = _compute_box(region)
    png = _grab_png_bytes(box)
    try:
        with open(SCREENSHOT_PATH, "wb") as fh:
            fh.write(png)
    except Exception:
        pass
    b64 = base64.b64encode(png).decode("ascii")
    write_screen_b64(b64)  # live dashboard feed
    return b64


def register(mcp) -> None:
    @mcp.tool()
    def capture_screen(region: str = "full") -> str:
        """Capture the screen and return it as a base64-encoded PNG data URI.

        region: "full" | "top-half" | "bottom-half" | "left-half" |
        "right-half", or a custom box as "x,y,width,height".
        The screenshot is also saved to /tmp/hermesvision_screen.png and pushed
        to the live dashboard feed. Returns a string starting with
        "data:image/png;base64,".
        """
        try:
            b64 = _capture(region)
            return emit_tool_call(
                "capture_screen",
                {"region": region},
                "data:image/png;base64," + b64,
            )
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call(
                "capture_screen", {"region": region}, f"ERROR: {exc}"
            )

    @mcp.tool()
    def get_screen_text(region: str = "full") -> str:
        """Capture the screen and run OCR (tesseract) to read on-screen text.

        region: same options as capture_screen. Returns the extracted plain
        text. Useful for reading the screen without a vision model. Requires
        the 'tesseract-ocr' system package.
        """
        try:
            box = _compute_box(region)
            png = _grab_png_bytes(box)
            import io

            from PIL import Image
            import pytesseract

            img = Image.open(io.BytesIO(png))
            text = pytesseract.image_to_string(img)
            text = text.strip() or "(no text detected on screen)"
            return emit_tool_call("get_screen_text", {"region": region}, text)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "tesseract" in msg.lower() and (
                "not installed" in msg.lower() or "not in your path" in msg.lower()
            ):
                msg = (
                    "tesseract is not installed. Install it with: "
                    "sudo apt-get install -y tesseract-ocr"
                )
            return emit_tool_call(
                "get_screen_text", {"region": region}, f"ERROR: {msg}"
            )

    @mcp.tool()
    def find_on_screen(description: str) -> str:
        """Capture the screen and return image + dimensions for locating things.

        Returns a JSON object: {"image": "<base64 PNG>", "screen_width": N,
        "screen_height": N, "description": "<what to find>"}. A vision-capable
        model can use the image and dimensions to compute click coordinates.
        """
        try:
            b64 = _capture("full")
            width, height = get_screen_size()
            payload = json.dumps(
                {
                    "image": b64,
                    "screen_width": width,
                    "screen_height": height,
                    "description": description,
                }
            )
            return emit_tool_call(
                "find_on_screen", {"description": description}, payload
            )
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call(
                "find_on_screen", {"description": description}, f"ERROR: {exc}"
            )
