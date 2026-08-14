# POR — Blender Addon (self-contained MCP server)

## Problem

The current architecture has three moving parts the user must wire together manually:

1. Install the external ahujasid/blender-mcp addon (TCP socket transport)
2. Start Claude Code from the synthgen project directory (so it picks up `.claude/mcp_servers.json`)
3. Manually start the socket server in Blender's N-panel

This is fragile and directory-dependent. If you're not in the right directory, nothing
works. The external addon is a black box that may break with Blender 5.x.

## Goal

A **single Blender addon** that bundles the entire synthgen MCP server. Install the addon
zip, enable it, and Claude Code can connect — no directory dependency, no external addon,
no manual process startup.

## Architecture

```
Claude Code ──(SSE HTTP)──► Blender addon
                              ├── SSE MCP server (background thread)
                              ├── Main-thread executor (bpy.app.timers)
                              ├── All 33 tools (schema, graph, blender, pipeline, verify)
                              ├── Bundled schema data (data/schemas/)
                              └── N-panel UI (status, port, config)
```

**Why SSE, not stdio:** The MCP server runs inside Blender's process, not as a
subprocess that Claude Code spawns. SSE (Server-Sent Events over HTTP) is a first-class
MCP transport that Claude Code supports. The addon starts an HTTP server on a local port
(default 8400) and Claude Code connects to `http://localhost:8400/sse`.

**Why not a subprocess bridge:** Adding a proxy process re-introduces the multi-process
fragility we're trying to eliminate. SSE is simpler and the `mcp` SDK supports it
natively via `mcp.run(transport="sse")`.

**Thread safety:** Blender's `bpy` API is main-thread-only. The SSE MCP server runs in
a background thread. All tool execution must be marshaled to the main thread via a
queue + `bpy.app.timers` polling loop. This is a well-established Blender addon pattern.

## Decisions locked

- **Transport:** SSE on localhost (configurable port, default 8400)
- **No ahujasid dependency:** The addon replaces it entirely
- **Bundled deps:** The `mcp` SDK and its dependency tree are vendored or pip-installed
  into the addon's own `site-packages/` on first enable
- **Schema data bundled:** `data/schemas/` ships inside the addon zip
- **DirectBpyTransport reused:** The existing `DirectBpyTransport` is the right shape
  for in-process execution — it just needs main-thread marshaling wrapped around it

## Stages

### Stage 1 — Addon skeleton + dependency management

#### 1.1 Addon structure

Create the addon package at `addon/synthgen_mcp/`:

```
addon/synthgen_mcp/
  __init__.py          # bl_info, register(), unregister(), preferences
  ui.py                # N-panel (status, port, copy config button)
  deps.py              # Dependency installer (pip into addon's vendor/)
  vendor/              # Vendored or pip-installed dependencies (gitignored)
  synthgen/             # Symlink or copy of src/synthgen/ for development
  data/schemas/        # Bundled schema JSON files
```

`bl_info` targets Blender 5.2+. The addon is a package (directory), not a single file,
so it installs as a zip via Edit → Preferences → Add-ons → Install.

**Files:** `addon/synthgen_mcp/__init__.py`, `addon/synthgen_mcp/ui.py`

**Validation:**
- [ ] Addon installs in Blender 5.2 via zip
- [ ] Enable/disable works without errors
- [ ] N-panel appears in 3D viewport sidebar

#### 1.2 Dependency management

The `mcp` SDK pulls in ~15 packages including compiled binaries (`pydantic-core`).
Strategy: on first enable, pip-install into the addon's own `vendor/` directory
using Blender's bundled Python. Show a progress indicator in the N-panel.

```python
import subprocess, sys
subprocess.check_call([
    sys.executable, "-m", "pip", "install",
    "--target", vendor_path,
    "mcp[cli]>=1.3.0,<2",
])
```

The `vendor/` directory is prepended to `sys.path` at addon load time. It's gitignored
(different Blender versions have different Python ABIs).

**Files:** `addon/synthgen_mcp/deps.py`

**Validation:**
- [ ] Dependencies install on first enable
- [ ] Subsequent enables skip installation (deps already present)
- [ ] Works with Blender 5.2's bundled Python (3.12+)

#### 1.3 Schema + synthgen bundling

Bundle `data/schemas/` inside the addon. Override `_schemas_root()` in `schema/query.py`
to resolve relative to the addon directory instead of the source tree. Use an environment
variable or a module-level override.

Bundle `src/synthgen/` inside the addon — either as a copy (for distribution) or a
symlink (for development). The build script handles this.

**Files:** `addon/synthgen_mcp/__init__.py` (path setup), build script

**Validation:**
- [ ] `schema_find` works from inside Blender
- [ ] Schema data loads for Blender 5.2

---

### Stage 2 — Main-thread executor

#### 2.1 Thread-safe execution queue

Build a queue-based executor that marshals Python code execution to Blender's main thread:

```python
import queue, threading

class MainThreadExecutor:
    def __init__(self):
        self._queue = queue.Queue()

    def submit(self, code: str) -> concurrent.futures.Future:
        """Submit code for main-thread execution. Returns a Future."""
        future = concurrent.futures.Future()
        self._queue.put((code, future))
        return future

    def poll(self):
        """Called by bpy.app.timers on the main thread."""
        while not self._queue.empty():
            code, future = self._queue.get_nowait()
            try:
                result = self._execute(code)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
        return 0.01  # poll every 10ms
```

Register the timer on addon enable, unregister on disable.

**Files:** `addon/synthgen_mcp/executor.py`

**Validation:**
- [ ] Code submitted from a background thread executes on the main thread
- [ ] Results are returned to the calling thread via Future
- [ ] Exceptions propagate correctly
- [ ] Timer unregisters cleanly on addon disable

#### 2.2 Executor-backed transport

Create `AddonTransport(TransportBackend)` that wraps `MainThreadExecutor`:

```python
class AddonTransport(TransportBackend):
    def __init__(self, executor: MainThreadExecutor):
        super().__init__()
        self._executor = executor

    def execute_python(self, code: str) -> dict | str:
        future = self._executor.submit(code)
        return future.result(timeout=180)  # match existing command timeout

    def get_blender_version(self) -> tuple:
        code = "import bpy; print(bpy.app.version[:])"
        result = self.execute_python(code)
        # parse version tuple from output
        ...
```

**Files:** `addon/synthgen_mcp/executor.py`

**Validation:**
- [ ] `AddonTransport.execute_python` works from a background thread
- [ ] `get_blender_version()` returns correct tuple
- [ ] Dirty flag tracking works (inherited from `TransportBackend`)

---

### Stage 3 — SSE MCP server

#### 3.1 Server startup

On addon enable (or when user clicks "Start Server" in the N-panel), launch the
FastMCP SSE server in a background daemon thread:

```python
import threading

def _start_server(port: int, executor: MainThreadExecutor):
    # Build FastMCP instance with AddonTransport
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("synthgen", ...)

    # Register all tool modules
    transport = AddonTransport(executor)
    schema_tools.register(mcp, ...)
    graph_tools.register(mcp, lambda: transport)
    blender_tools.register(mcp, lambda: transport, ...)
    pipeline_tools.register(mcp, lambda: transport, ...)
    verify_tools.register(mcp, lambda: transport)

    # Run SSE server (blocking — runs in daemon thread)
    mcp.run(transport="sse", host="127.0.0.1", port=port)

server_thread = threading.Thread(target=_start_server, args=(port, executor), daemon=True)
server_thread.start()
```

The daemon thread dies automatically when Blender exits. The N-panel shows
"Server running on port 8400" or "Server stopped".

**Files:** `addon/synthgen_mcp/server.py`, `addon/synthgen_mcp/__init__.py`

**Validation:**
- [ ] Server starts on addon enable
- [ ] Server stops on addon disable
- [ ] `http://localhost:8400/sse` responds to MCP handshake
- [ ] Multiple start/stop cycles work without port conflicts

#### 3.2 Tool registration + schema resolution

Wire all 33 tools through the `AddonTransport`. Schema resolution uses the addon's
bundled data directory instead of the source tree path.

Override `_get_blender_dir` to use `resolve_schema_dir(bpy.app.version)` directly
(no transport round-trip needed — we're inside Blender).

**Files:** `addon/synthgen_mcp/server.py`

**Validation:**
- [ ] All 33 tools respond correctly via SSE MCP
- [ ] Schema grounding validates node types against bundled schema
- [ ] Graph introspection tools work (LiveGraph via main-thread execution)

---

### Stage 4 — UI + configuration

#### 4.1 N-panel

Blender sidebar panel (`VIEW3D_PT_synthgen_mcp`) showing:

- Server status (running/stopped) with start/stop button
- Port number (editable in addon preferences)
- Connection count (number of active SSE clients)
- "Copy MCP Config" button — copies the Claude Code config JSON to clipboard:
  ```json
  {"synthgen": {"url": "http://localhost:8400/sse"}}
  ```
- Link to docs / help

**Files:** `addon/synthgen_mcp/ui.py`

**Validation:**
- [ ] Panel renders correctly
- [ ] Start/stop button toggles server
- [ ] Copy config button works
- [ ] Status updates in real-time

#### 4.2 Addon preferences

In Edit → Preferences → Add-ons → Synthgen MCP:

- Port number (default 8400)
- Auto-start server on addon enable (default True)
- Log level (default WARNING)

**Files:** `addon/synthgen_mcp/__init__.py`

**Validation:**
- [ ] Preferences persist across Blender restarts
- [ ] Port change takes effect on next server start
- [ ] Auto-start works on Blender launch

---

### Stage 5 — Build + packaging

#### 5.1 Build script

A script that creates the distributable addon zip:

1. Creates a clean `synthgen_mcp/` directory
2. Copies `src/synthgen/` into it
3. Copies `data/schemas/` into it
4. Copies addon files (`__init__.py`, `ui.py`, `deps.py`, `executor.py`, `server.py`)
5. Zips it as `synthgen_mcp.zip`

The `vendor/` directory is NOT included in the zip — dependencies are installed
on first enable to match the target Blender's Python ABI.

**Files:** `scripts/build_addon.py`

**Validation:**
- [ ] `synthgen_mcp.zip` installs cleanly in Blender 5.2
- [ ] Full end-to-end test: install zip → enable → Claude Code connects → run tools

#### 5.2 Documentation

- Installation instructions in `addon/README.md`
- Update project `README.md` with addon section
- Update `ROADMAP.md`

**Files:** `addon/README.md`, `README.md`, `ROADMAP.md`

---

## Definition of done

### Stage 1
- [ ] Addon installs and enables in Blender 5.2
- [ ] Dependencies install via pip on first enable
- [ ] Schema data bundled and loadable

### Stage 2
- [ ] Main-thread executor works from background threads
- [ ] AddonTransport passes all execution to main thread
- [ ] Timer lifecycle is clean (register/unregister)

### Stage 3
- [ ] SSE MCP server starts/stops cleanly
- [ ] All 33 tools callable via MCP over SSE
- [ ] Claude Code can connect and use tools

### Stage 4
- [ ] N-panel shows status and config
- [ ] Preferences work correctly
- [ ] Copy-to-clipboard generates correct MCP config

### Stage 5
- [ ] Build script produces installable zip
- [ ] End-to-end: fresh Blender → install zip → enable → Claude Code → create object in Blender
- [ ] Documentation complete

## Risks

### pydantic-core ABI compatibility
`pydantic-core` is a compiled Rust extension. The wheel must match Blender's bundled
Python version exactly (3.12.x for Blender 5.2). If pip can't find a compatible wheel,
the dependency install fails. Mitigation: test with Blender 5.2's exact Python version;
fall back to a pure-Python pydantic shim if needed.

### bpy.app.timers latency
The poll interval (10ms) adds latency to every tool call. For most tools this is
negligible. For `sweep` (which renders many frames), the single-call architecture
means the latency is paid once, not per-frame. If 10ms is too coarse for interactive
feel, it can be reduced to 1ms.

### SSE server shutdown
`FastMCP.run(transport="sse")` may not expose a clean shutdown hook. If the underlying
uvicorn server doesn't stop gracefully, port conflicts occur on re-enable. Mitigation:
track the server thread and forcibly terminate if needed; use SO_REUSEADDR.

### Blender's Python environment
Blender ships its own Python with a limited `site-packages`. pip-installing into a
custom target directory avoids polluting Blender's environment but requires careful
`sys.path` management to avoid conflicts with Blender's own packages.

## Key context

- Read `dev_tasks/003_mcp_stabilize_and_ground/HANDOFF.md` for the MCP server architecture
- Read `src/synthgen/mcp/transport.py` for transport backends
- Read `knowledge/procedural_paradigm.md` for the procedural-first philosophy
- `mcp` SDK docs: `FastMCP` supports `transport="sse"` for HTTP-based serving
- Blender 5.2 ships Python 3.12.x
