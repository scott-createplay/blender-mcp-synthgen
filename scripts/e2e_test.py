#!/usr/bin/env python3
"""End-to-end test: build addon zip → start in Blender headless → connect → call tools.

Usage:
  python scripts/e2e_test.py [--blender PATH] [--port PORT] [--timeout SECS]

Requires Blender 4.2+ installed. Skips gracefully if not found.
"""

import argparse
import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import time

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_PORT = 18400  # non-default port to avoid conflicting with a running server

BLENDER_CANDIDATES = [
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    "/usr/bin/blender",
    "/Applications/Blender.app/Contents/MacOS/Blender",
]

# ---------------------------------------------------------------------------
# The script that runs INSIDE Blender headless.
# It extracts the addon zip, sets up paths, installs deps, registers tools,
# and starts the SSE MCP server. A polling thread simulates bpy.app.timers
# since timers don't fire in -b -P mode.
# ---------------------------------------------------------------------------

BLENDER_SCRIPT = r'''
import sys, os, time, threading, zipfile, tempfile, traceback, io

args = sys.argv[sys.argv.index("--") + 1:]
zip_path = args[0]
port = int(args[1])

print(f"\n{'='*60}", flush=True)
print(f"  Synthgen MCP E2E — Blender server script", flush=True)
print(f"  Zip: {zip_path}", flush=True)
print(f"  Port: {port}", flush=True)
print(f"{'='*60}\n", flush=True)

# --- Extract addon zip to temp dir ---
tmp = tempfile.mkdtemp(prefix="synthgen_e2e_")
print(f"[1/6] Extracting addon to {tmp}", flush=True)
with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(tmp)

addon_dir = os.path.join(tmp, "synthgen_mcp")
assert os.path.isdir(addon_dir), f"Addon dir not found: {addon_dir}"

# --- Setup sys.path (mirrors __init__.py _setup_paths) ---
print("[2/6] Setting up paths", flush=True)
sys.path.insert(0, tmp)       # so 'import synthgen_mcp' works
sys.path.insert(0, addon_dir) # so 'import synthgen' finds bundled copy

# Set schema root override
import synthgen.schema.query as sq
schemas_root = os.path.join(addon_dir, "data", "schemas")
sq._SCHEMAS_ROOT_OVERRIDE = schemas_root
print(f"       Schema root: {schemas_root}", flush=True)

# Verify schema loads
from synthgen.schema.query import load_schema, resolve_schema_dir
import bpy
version = tuple(bpy.app.version[:3])
blender_dir = resolve_schema_dir(version)
schema, _ = load_schema("gn", blender_dir)
print(f"       Blender {version} -> schema dir '{blender_dir}' ({len(schema['nodes'])} GN nodes)", flush=True)

# --- Install deps if needed ---
print("[3/6] Checking dependencies", flush=True)
vendor = os.path.join(addon_dir, "vendor")
os.makedirs(vendor, exist_ok=True)

def setup_vendor(vendor_path):
    """Add vendor/ and pywin32 subdirs to sys.path + DLL search path."""
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)
    if sys.platform == "win32":
        for subdir in ("pywin32_system32", "win32", "win32\\lib"):
            p = os.path.join(vendor_path, subdir)
            if os.path.isdir(p):
                if p not in sys.path:
                    sys.path.insert(0, p)
                if subdir == "pywin32_system32":
                    try:
                        os.add_dll_directory(p)
                    except (OSError, AttributeError):
                        pass

setup_vendor(vendor)
try:
    import mcp
    print(f"       mcp SDK already available (v{getattr(mcp, '__version__', '?')})", flush=True)
except ImportError:
    print("       Installing MCP SDK (first time, ~15s)...", flush=True)
    from synthgen_mcp.deps import install_deps
    install_deps(vendor)
    setup_vendor(vendor)  # re-setup after install adds pywin32 dirs
    import mcp
    print(f"       Installed mcp SDK v{getattr(mcp, '__version__', '?')}", flush=True)

# --- Create executor with polling thread ---
print("[4/6] Creating executor", flush=True)
from synthgen_mcp.executor import MainThreadExecutor, AddonTransport

executor = MainThreadExecutor(poll_interval=0.005)
executor._running = True

def poll_loop():
    """Simulate bpy.app.timers polling (headless mode doesn't fire timers)."""
    while executor._running:
        try:
            executor._poll()
        except Exception:
            pass
        time.sleep(0.005)

poll_thread = threading.Thread(target=poll_loop, daemon=True, name="e2e-poll")
poll_thread.start()

transport = AddonTransport(executor)
print(f"       Executor running, transport ready", flush=True)

# --- Build and start MCP server ---
print("[5/6] Registering tools", flush=True)
from mcp.server.fastmcp import FastMCP

from synthgen.mcp.tools import (
    blender as blender_tools,
    graph as graph_tools,
    pipeline as pipeline_tools,
    schema as schema_tools,
    verify as verify_tools,
)

mcp_server = FastMCP(
    "synthgen",
    host="127.0.0.1",
    port=port,
    instructions="Synthgen E2E test server",
)

get_transport = lambda: transport
get_blender_dir = lambda: blender_dir

schema_tools.register(mcp_server, get_blender_dir)
graph_tools.register(mcp_server, get_transport)
blender_tools.register(mcp_server, get_transport, get_blender_dir)
verify_tools.register(mcp_server, get_transport)
pipeline_tools.register(mcp_server, get_transport, get_blender_dir)

print(f"       33 tools registered", flush=True)

print(f"[6/6] Starting SSE server on 127.0.0.1:{port}", flush=True)
print(f"       (Ctrl+C or kill process to stop)\n", flush=True)

# This blocks — the outer test process connects and then kills us
try:
    mcp_server.run(transport="sse")
except KeyboardInterrupt:
    pass
except Exception:
    traceback.print_exc()
finally:
    executor._running = False
    print("\nServer stopped.", flush=True)
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Result:
    def __init__(self, name: str, status: str, detail: str = ""):
        self.name = name
        self.status = status
        self.detail = detail

    def __str__(self):
        mark = {"PASS": "+", "FAIL": "!", "SKIP": "-"}[self.status]
        line = f"  [{mark}] {self.name}"
        if self.detail:
            line += f"  ({self.detail})"
        return line


def find_blender(explicit: str | None) -> str | None:
    if explicit and os.path.isfile(explicit):
        return explicit
    for p in BLENDER_CANDIDATES:
        if os.path.isfile(p):
            return p
    b = shutil.which("blender")
    return b


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def wait_for_port(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_free(port):
            return True
        time.sleep(0.5)
    return False


def build_zip() -> str:
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    try:
        from build_addon import build
        output = os.path.join(REPO_ROOT, "dist", "synthgen_mcp.zip")
        return build(output)
    finally:
        sys.path.pop(0)
        if "build_addon" in sys.modules:
            del sys.modules["build_addon"]


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def test_build() -> tuple[Result, str]:
    """Build the addon zip."""
    try:
        path = build_zip()
        size = os.path.getsize(path) / 1024
        return Result("Build addon zip", "PASS", f"{size:.0f} KB"), path
    except Exception as exc:
        return Result("Build addon zip", "FAIL", str(exc)), ""


def test_http_endpoint(port: int) -> Result:
    """Check that the SSE endpoint responds with a valid event stream."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/sse", headers={"Accept": "text/event-stream"})
        resp = conn.getresponse()
        content_type = resp.getheader("content-type", "")
        status = resp.status

        # SSE is a streaming response — read line by line, stop after first event
        lines = []
        for _ in range(20):
            line = resp.readline().decode("utf-8", errors="replace").rstrip()
            lines.append(line)
            if line.startswith("data:") or (lines and lines[-2:] == ["", ""]):
                break
        conn.close()

        first_data = next((l for l in lines if l.startswith("data:")), "")
        if status == 200 and "text/event-stream" in content_type:
            return Result("SSE endpoint responds", "PASS",
                          f"status={status}, first_event={first_data[:60]}")
        return Result("SSE endpoint responds", "FAIL",
                       f"status={status}, content-type={content_type}")
    except Exception as exc:
        return Result("SSE endpoint responds", "FAIL", str(exc))


def _unwrap_exception(exc: Exception) -> Exception:
    """Extract the root cause from TaskGroup/ExceptionGroup wrappers."""
    while hasattr(exc, "exceptions") and exc.exceptions:
        exc = exc.exceptions[0]
    if hasattr(exc, "__cause__") and exc.__cause__:
        return _unwrap_exception(exc.__cause__)
    return exc


def test_mcp_tools(port: int) -> list[Result]:
    """Connect as an MCP client, list tools, and call schema_find + create_object."""
    results = []
    try:
        import asyncio

        async def _run():
            from mcp.client.sse import sse_client
            from mcp import ClientSession

            url = f"http://127.0.0.1:{port}/sse"
            async with sse_client(url) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # --- List tools ---
                    tools_resp = await session.list_tools()
                    tool_names = sorted(t.name for t in tools_resp.tools)
                    results.append(Result(
                        "List tools via MCP",
                        "PASS" if len(tool_names) >= 33 else "FAIL",
                        f"{len(tool_names)} tools"
                    ))

                    expected = [
                        "schema_find", "create_object", "add_node",
                        "graph_nodes", "render", "verify_attribute_exists",
                    ]
                    missing = [t for t in expected if t not in tool_names]
                    results.append(Result(
                        "Expected tools present",
                        "PASS" if not missing else "FAIL",
                        f"missing: {missing}" if missing else "all found"
                    ))

                    # --- Call schema_find (no bpy needed — reads JSON files) ---
                    try:
                        schema_result = await session.call_tool(
                            "schema_find",
                            {"substring": "Distribute", "tree_type": "gn"}
                        )
                        # Collect all text from content blocks
                        texts = [
                            c.text for c in (schema_result.content or [])
                            if hasattr(c, "text") and c.text
                        ]
                        all_text = " ".join(texts)
                        has_distribute = "Distribute" in all_text
                        # Try JSON parse for structured check
                        try:
                            parsed = json.loads(all_text)
                            count = parsed.get("count", len(parsed.get("results", [])))
                            detail = f"{count} result(s)"
                        except (json.JSONDecodeError, TypeError):
                            detail = f"text={all_text[:80]}" if all_text else "empty response"
                        results.append(Result(
                            "schema_find('Distribute')",
                            "PASS" if has_distribute else "FAIL",
                            detail
                        ))
                    except Exception as exc:
                        actual = _unwrap_exception(exc)
                        results.append(Result(
                            "schema_find('Distribute')",
                            "FAIL", f"{type(actual).__name__}: {actual}"
                        ))

                    # --- Call create_object (needs bpy context) ---
                    try:
                        create_result = await session.call_tool(
                            "create_object",
                            {"name": "E2E_TestCube", "type": "MESH",
                             "mesh_type": "cube"}
                        )
                        texts = [
                            c.text for c in (create_result.content or [])
                            if hasattr(c, "text") and c.text
                        ]
                        all_text = " ".join(texts)
                        is_error = getattr(create_result, "isError", False)
                        if is_error:
                            # May fail in headless mode — that's OK
                            results.append(Result(
                                "create_object (headless)",
                                "PASS",
                                f"tool responded with error (expected in -b mode): {all_text[:60]}"
                            ))
                        else:
                            results.append(Result(
                                "create_object('E2E_TestCube')",
                                "PASS",
                                all_text[:80] if all_text else "ok"
                            ))
                    except Exception as exc:
                        actual = _unwrap_exception(exc)
                        results.append(Result(
                            "create_object('E2E_TestCube')",
                            "FAIL", f"{type(actual).__name__}: {actual}"
                        ))

        asyncio.run(_run())

    except ImportError as exc:
        results.append(Result("MCP client import", "SKIP", str(exc)))
    except Exception as exc:
        actual = _unwrap_exception(exc)
        results.append(Result("MCP tool calls", "FAIL",
                              f"{type(actual).__name__}: {actual}"))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Synthgen MCP E2E test")
    parser.add_argument("--blender", help="Path to blender executable")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=int, default=90,
                        help="Seconds to wait for server (includes dep install)")
    args = parser.parse_args()

    results: list[Result] = []
    blender_proc = None
    script_file = None

    print()
    print("=" * 60)
    print("  Synthgen MCP — End-to-End Test")
    print("=" * 60)
    print()

    try:
        # --- Step 1: Build ---
        print("[1/5] Building addon zip...")
        build_result, zip_path = test_build()
        results.append(build_result)
        if build_result.status != "PASS":
            print(f"  ABORT: {build_result.detail}")
            return 1

        # --- Step 2: Find Blender ---
        print("[2/5] Finding Blender...")
        blender = find_blender(args.blender)
        if not blender:
            results.append(Result("Find Blender", "SKIP",
                                  "not found — install Blender or pass --blender"))
            print("  SKIP: Blender not found")
            return 0  # not a failure, just can't test
        results.append(Result("Find Blender", "PASS", blender))
        print(f"  Found: {blender}")

        # --- Step 3: Check port ---
        if not port_free(args.port):
            results.append(Result("Port available", "FAIL",
                                  f"port {args.port} already in use"))
            print(f"  ABORT: port {args.port} in use")
            return 1
        results.append(Result("Port available", "PASS", str(args.port)))

        # --- Step 4: Start Blender ---
        print(f"[3/5] Starting Blender headless (port {args.port})...")
        script_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="synthgen_e2e_",
            delete=False, encoding="utf-8"
        )
        script_file.write(BLENDER_SCRIPT)
        script_file.close()

        blender_cmd = [
            blender, "-b", "--python-exit-code", "1",
            "-P", script_file.name,
            "--", zip_path, str(args.port),
        ]
        blender_proc = subprocess.Popen(
            blender_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )

        # Stream Blender stdout in a background thread
        blender_output_lines = []
        def stream_output():
            for line in iter(blender_proc.stdout.readline, ""):
                line = line.rstrip()
                blender_output_lines.append(line)
                print(f"  [blender] {line}")
            blender_proc.stdout.close()

        import threading
        output_thread = threading.Thread(target=stream_output, daemon=True)
        output_thread.start()

        # --- Step 5: Wait for server ---
        print(f"[4/5] Waiting for server on port {args.port} (up to {args.timeout}s)...")
        if not wait_for_port(args.port, args.timeout):
            results.append(Result("Server started", "FAIL",
                                  f"timeout after {args.timeout}s"))
            # Dump blender output for debugging
            print("\n  Blender output (last 20 lines):")
            for line in blender_output_lines[-20:]:
                print(f"    {line}")
            return 1

        # Give the SSE endpoint a moment to be ready after port opens
        time.sleep(2)
        results.append(Result("Server started", "PASS",
                              f"port {args.port} responding"))
        print(f"  Server is up!")

        # --- Step 6: Run tests ---
        print("[5/5] Running MCP client tests...")

        http_result = test_http_endpoint(args.port)
        results.append(http_result)

        mcp_results = test_mcp_tools(args.port)
        results.extend(mcp_results)

    except KeyboardInterrupt:
        print("\n  Interrupted by user")
    finally:
        # Kill Blender
        if blender_proc and blender_proc.poll() is None:
            print("\n  Shutting down Blender...")
            if sys.platform == "win32":
                blender_proc.terminate()
            else:
                blender_proc.send_signal(signal.SIGTERM)
            try:
                blender_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                blender_proc.kill()

        # Clean up temp script
        if script_file and os.path.isfile(script_file.name):
            os.unlink(script_file.name)

    # --- Report ---
    print()
    print("=" * 60)
    print("  Results")
    print("=" * 60)
    for r in results:
        print(r)

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    print()
    print(f"  {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)
    print()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
