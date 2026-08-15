"""Validate the Synthgen MCP addon: health, SSE connectivity, MCP tool call.

Usage:  python tools/validate_addon.py
        python tools/validate_addon.py --port 9000

Requires the addon to be running inside Blender (N-panel → Start Server).
Checks three stages:
  1. GET /health  — server up, tools registered, no errors
  2. SSE connect  — /sse returns an endpoint event
  3. MCP tool call — full JSON-RPC handshake + schema_find("Distribute")
"""

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def _header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ── Stage 1: Health endpoint ────────────────────────────────────


def check_health(base: str) -> tuple[str, str]:
    _header("Stage 1: Health endpoint")
    try:
        resp = urllib.request.urlopen(f"{base}/health", timeout=5)
        data = json.loads(resp.read())
        print(f"  status:          {data.get('status')}")
        print(f"  port:            {data.get('port')}")
        print(f"  tools:           {data.get('tools')}")
        print(f"  tools_hash:      {data.get('tools_hash', 'n/a')}")
        print(f"  addon_version:   {data.get('addon_version', 'n/a')}")
        print(f"  blender_version: {data.get('blender_version', 'n/a')}")
        print(f"  uptime:          {data.get('uptime_seconds')}s")
        if data.get("error"):
            print(f"  error:           {data['error']}")

        if data.get("status") != "ok":
            return FAIL, "status is not 'ok'"
        if (data.get("tools") or 0) == 0:
            return FAIL, "no tools registered"
        return PASS, ""
    except urllib.error.HTTPError as e:
        return FAIL, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return FAIL, f"Connection failed — is the addon running? ({e.reason})"
    except Exception as e:
        return FAIL, str(e)


# ── Stage 2: SSE connectivity ──────────────────────────────────


def check_sse(base: str) -> tuple[str, str]:
    _header("Stage 2: SSE connectivity")
    endpoint: list[str | None] = [None]
    error: list[str | None] = [None]

    def reader():
        try:
            resp = urllib.request.urlopen(f"{base}/sse", timeout=10)
            event_type = None
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    if event_type == "endpoint":
                        endpoint[0] = line[6:]
                        return
        except Exception as e:
            error[0] = str(e)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout=10)

    if endpoint[0]:
        print(f"  endpoint: {endpoint[0]}")
        return PASS, endpoint[0]
    if error[0]:
        return FAIL, error[0]
    return FAIL, "Timed out waiting for endpoint event"


# ── Stage 3: MCP tool call ──────────────────────────────────────


def check_mcp(base: str) -> tuple[str, str]:
    _header("Stage 3: MCP tool call (schema_find)")

    events: queue.Queue[tuple[str, str]] = queue.Queue()
    endpoint_holder: list[str | None] = [None]
    stop = threading.Event()

    def sse_reader():
        try:
            resp = urllib.request.urlopen(f"{base}/sse", timeout=60)
            event_type: str | None = None
            data_lines: list[str] = []
            for raw in resp:
                if stop.is_set():
                    return
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("event: "):
                    event_type = line[7:]
                    data_lines = []
                elif line.startswith("data: "):
                    data_lines.append(line[6:])
                elif line == "":
                    if event_type and data_lines:
                        payload = "\n".join(data_lines)
                        if event_type == "endpoint":
                            endpoint_holder[0] = payload
                        events.put((event_type, payload))
                    event_type = None
                    data_lines = []
        except Exception as e:
            if not stop.is_set():
                events.put(("_error", str(e)))

    t = threading.Thread(target=sse_reader, daemon=True)
    t.start()

    def wait_event(match: str, timeout: float = 15) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                etype, edata = events.get(timeout=0.5)
                if etype == "_error":
                    raise RuntimeError(edata)
                if etype == match:
                    return edata
            except queue.Empty:
                continue
        raise TimeoutError(f"Timeout waiting for '{match}' event")

    def post(url: str, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)

    try:
        wait_event("endpoint", timeout=10)
        messages_url = f"{base}{endpoint_holder[0]}"
        print(f"  messages: {messages_url}")

        # ── initialize ──
        post(messages_url, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "validate_addon", "version": "1.0.0"},
            },
        })
        init_data = json.loads(wait_event("message", timeout=10))
        server_name = (
            init_data.get("result", {}).get("serverInfo", {}).get("name", "?")
        )
        print(f"  server:   {server_name}")

        # ── initialized notification ──
        post(messages_url, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        # ── tools/list ──
        post(messages_url, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        list_data = json.loads(wait_event("message", timeout=10))
        tools = list_data.get("result", {}).get("tools", [])
        tool_names = [t["name"] for t in tools]
        print(f"  tools:    {len(tool_names)}")

        if "schema_find" not in tool_names:
            return FAIL, f"schema_find not in tool list ({len(tool_names)} tools)"

        # ── tools/call schema_find ──
        post(messages_url, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "schema_find",
                "arguments": {"substring": "Distribute"},
            },
        })
        call_data = json.loads(wait_event("message", timeout=15))

        if "error" in call_data:
            return FAIL, f"Tool error: {call_data['error']}"

        content = call_data.get("result", {}).get("content", [])
        if not content:
            return FAIL, "Empty response from schema_find"

        text = content[0].get("text", "")
        if "Distribute" not in text:
            return FAIL, f"Unexpected response: {text[:200]}"

        preview = text[:200] + "..." if len(text) > 200 else text
        print(f"  result:   {preview}")
        return PASS, ""

    except (TimeoutError, RuntimeError) as e:
        return FAIL, str(e)
    finally:
        stop.set()


# ── Main ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SYNTHGEN_PORT", "8400")),
        help="MCP server port (default: 8400 or $SYNTHGEN_PORT)",
    )
    args = parser.parse_args()
    base = f"http://localhost:{args.port}"

    print(f"Validating Synthgen MCP addon at {base}")

    results: list[tuple[str, str]] = []

    # Stage 1
    status, detail = check_health(base)
    print(f"\n  -> {status}" + (f"  {detail}" if detail else ""))
    results.append(("Health", status))

    # Stage 2
    status, detail = check_sse(base)
    print(f"\n  -> {status}" + (f"  {detail}" if detail else ""))
    results.append(("SSE", status))

    # Stage 3 (skip if SSE failed)
    if results[-1][1] == FAIL:
        _header("Stage 3: MCP tool call (schema_find)")
        print("  SKIP — SSE connectivity failed")
        results.append(("MCP call", SKIP))
    else:
        status, detail = check_mcp(base)
        print(f"\n  -> {status}" + (f"  {detail}" if detail else ""))
        results.append(("MCP call", status))

    # Summary
    icons = {PASS: "+", FAIL: "x", SKIP: "-"}
    print(f"\n{'=' * 60}")
    print("  Summary")
    print(f"{'=' * 60}")
    for name, s in results:
        print(f"  [{icons.get(s, '?')}] {name}: {s}")

    print()
    if all(s == PASS for _, s in results):
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
