"""Playwright (headless Chromium) browser control.

A single browser instance is created lazily on first use and reused across
calls. Playwright's sync objects are NOT thread-safe and must be touched from
the one thread that created them, but FastMCP runs sync tools on an arbitrary
worker-thread pool. We therefore funnel ALL Playwright work through a dedicated
single-thread executor so every call runs on the same thread.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor

from mcp_server.tools.permissions import permission_gate
from dashboard.websocket_manager import emit_tool_call

# One thread owns the whole Playwright object graph.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hv-browser")
_pw = None  # playwright context manager handle
_browser = None
_page = None
_MAX_TEXT = 10000


def _run(fn):
    """Run ``fn`` on the dedicated browser thread and return its result."""
    return _executor.submit(fn).result()


def _ensure_page():
    """(browser thread) Return the live page, creating the browser if needed."""
    global _pw, _browser, _page
    if _page is not None:
        return _page
    from playwright.sync_api import sync_playwright

    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=True)
    _page = _browser.new_page()
    return _page


def _require_page():
    """(browser thread) Return the page or raise if no page is open yet."""
    if _page is None:
        raise RuntimeError("no browser page is open - call browser_open(url) first")
    return _page


def _close():
    """(browser thread) Tear down the browser."""
    global _pw, _browser, _page
    try:
        if _browser is not None:
            _browser.close()
    finally:
        if _pw is not None:
            try:
                _pw.stop()
            except Exception:
                pass
        _pw = _browser = _page = None


def register(mcp) -> None:
    @mcp.tool()
    def browser_open(url: str) -> str:
        """Open a URL in a headless Chromium browser and wait for it to settle.

        Reuses one browser across calls. Requires the 'browser_navigate'
        permission. Returns "Opened: <url> | Title: <page title>".
        """
        params = {"url": url}
        denied = permission_gate("browser_navigate")
        if denied:
            return emit_tool_call("browser_open", params, denied)

        if "://" not in url:
            url = "https://" + url

        def _op():
            page = _ensure_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            return page.title()

        try:
            title = _run(_op)
            return emit_tool_call("browser_open", params, f"Opened: {url} | Title: {title}")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("browser_open", params, f"ERROR: {exc}")

    @mcp.tool()
    def browser_screenshot() -> str:
        """Screenshot the current browser page; returns a base64-encoded PNG."""
        def _op():
            page = _require_page()
            return page.screenshot(type="png")

        try:
            png = _run(_op)
            b64 = base64.b64encode(png).decode("ascii")
            return emit_tool_call("browser_screenshot", {}, b64)
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("browser_screenshot", {}, f"ERROR: {exc}")

    @mcp.tool()
    def browser_click(selector: str) -> str:
        """Click an element on the page.

        selector may be a CSS selector or a text selector like "text=Submit".
        """
        params = {"selector": selector}

        def _op():
            page = _require_page()
            page.click(selector, timeout=15000)

        try:
            _run(_op)
            return emit_tool_call("browser_click", params, f"Clicked: {selector}")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("browser_click", params, f"ERROR: {exc}")

    @mcp.tool()
    def browser_type(selector: str, text: str) -> str:
        """Type text into an input matching selector (the field is cleared first)."""
        params = {"selector": selector, "text": text}

        def _op():
            page = _require_page()
            page.fill(selector, text, timeout=15000)

        try:
            _run(_op)
            return emit_tool_call("browser_type", params, f"Typed into {selector}")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("browser_type", params, f"ERROR: {exc}")

    @mcp.tool()
    def browser_get_text() -> str:
        """Return the visible text of the current page (scripts/styles excluded).

        Truncated to 10000 characters.
        """
        def _op():
            page = _require_page()
            return page.inner_text("body")

        try:
            text = _run(_op)
            if len(text) > _MAX_TEXT:
                text = text[:_MAX_TEXT] + "\n[...truncated...]"
            return emit_tool_call("browser_get_text", {}, text)
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("browser_get_text", {}, f"ERROR: {exc}")

    @mcp.tool()
    def browser_close() -> str:
        """Close the headless browser instance and free its resources."""
        try:
            _run(_close)
            return emit_tool_call("browser_close", {}, "Browser closed")
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("browser_close", {}, f"ERROR: {exc}")
