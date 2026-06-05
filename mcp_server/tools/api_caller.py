"""Generic HTTP API call tool."""

from __future__ import annotations

import json

from dashboard.websocket_manager import emit_tool_call

_MAX_BODY = 50 * 1024  # 50 KB


def register(mcp) -> None:
    @mcp.tool()
    def http_request(
        url: str,
        method: str = "GET",
        headers: str = "{}",
        body: str = "",
        timeout: int = 30,
    ) -> str:
        """Make an HTTP request and return the response as JSON.

        method: GET/POST/PUT/PATCH/DELETE/etc. headers is a JSON object string
        (e.g. '{"Authorization": "Bearer x"}'). body is the raw request body
        string (sent as-is). Returns JSON: {"status": <int>, "headers": {...},
        "body": "<text>"}. The response body is capped at 50KB.
        """
        params = {"url": url, "method": method.upper()}
        try:
            import httpx

            try:
                hdrs = json.loads(headers) if headers and headers.strip() else {}
                if not isinstance(hdrs, dict):
                    return emit_tool_call(
                        "http_request", params, "ERROR: headers must be a JSON object"
                    )
            except json.JSONDecodeError as exc:
                return emit_tool_call(
                    "http_request", params, f"ERROR: invalid headers JSON: {exc}"
                )

            content = body.encode("utf-8") if body else None
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.request(
                    method.upper(), url, headers=hdrs, content=content
                )

            text = resp.text
            if len(text) > _MAX_BODY:
                text = text[:_MAX_BODY] + "\n[...truncated to 50KB...]"

            payload = json.dumps(
                {
                    "status": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": text,
                }
            )
            return emit_tool_call("http_request", params, payload)
        except Exception as exc:  # noqa: BLE001
            return emit_tool_call("http_request", params, f"ERROR: {exc}")
