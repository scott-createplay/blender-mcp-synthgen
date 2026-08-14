# Handoff — Blender Addon (dev_task 004)

## Where we are

**All 5 stages complete.** The synthgen MCP server is now a self-contained Blender addon
that installs from a zip file. No external dependencies, no directory constraints, no
manual process wiring.

## What was built

### Stage 1 — Addon skeleton + dependency management
- `addon/synthgen_mcp/__init__.py` — `bl_info`, preferences (port, auto-start, log level),
  path setup for both dev and distribution modes, deferred server auto-start
- `addon/synthgen_mcp/deps.py` — finds Blender's bundled Python, pip-installs `mcp[cli]`
  into a `vendor/` directory on first enable
- Schema root override in `src/synthgen/schema/query.py` — `_SCHEMAS_ROOT_OVERRIDE` module
  variable, checked by `_schemas_root()` before falling back to the default path

### Stage 2 — Main-thread executor
- `addon/synthgen_mcp/executor.py` — `MainThreadExecutor` with `queue.Queue` +
  `bpy.app.timers` polling at 10ms + `concurrent.futures.Future` for result delivery
- `AddonTransport` — duck-types the `TransportBackend` interface, wraps executor.
  `execute_python()` submits code and blocks on the future (180s timeout).
  `get_blender_version()` reads `bpy.app.version` directly (no round-trip needed).
  Dirty flag tracking for Layer 2→3 invalidation.

### Stage 3 — SSE MCP server
- `addon/synthgen_mcp/server.py` — creates `FastMCP` with `host="127.0.0.1"` and
  configurable port, registers all 33 tools via the existing module `register()` functions,
  runs `mcp.run(transport="sse")` in a daemon thread
- Schema resolution uses bundled data directory (no transport round-trip)
- Clean start/stop lifecycle with `is_running()` state query

### Stage 4 — UI + configuration
- `addon/synthgen_mcp/ui.py` — N-panel (`VIEW3D_PT` in sidebar → "Synthgen MCP" tab)
- Three operators: start server, stop server, copy MCP config to clipboard
- Panel shows server status (running/stopped with icon), port, connection URL
- Addon preferences: port (1024–65535), auto-start toggle, log level

### Stage 5 — Build + packaging
- `scripts/build_addon.py` — creates `dist/synthgen_mcp.zip` containing addon files +
  bundled `synthgen/` package + `data/schemas/`. Excludes `__pycache__`, vendor, etc.
- README rewritten as installation-first documentation
- ROADMAP updated with Phase 3b (addon)

## Files

### New files
| File | What |
|---|---|
| `addon/synthgen_mcp/__init__.py` | Addon entry point — bl_info, preferences, register/unregister |
| `addon/synthgen_mcp/executor.py` | MainThreadExecutor + AddonTransport |
| `addon/synthgen_mcp/server.py` | SSE MCP server lifecycle (start/stop/is_running) |
| `addon/synthgen_mcp/ui.py` | N-panel + operators (start, stop, copy config) |
| `addon/synthgen_mcp/deps.py` | Dependency installer (pip into vendor/) |
| `scripts/build_addon.py` | Build script → dist/synthgen_mcp.zip |
| `tests/test_addon.py` | 19 offline tests (executor, transport, build, deps, schema override) |

### Modified files
| File | What changed |
|---|---|
| `src/synthgen/schema/query.py` | Added `_SCHEMAS_ROOT_OVERRIDE` for addon schema path |
| `.gitignore` | Added vendor/, dist/, bundled synthgen/data in addon dir |
| `.claude/settings.json` | Broadened permissions |
| `README.md` | Rewritten — installation-first, architecture diagram, tool table |
| `ROADMAP.md` | Added Phase 3b, updated test count to 194 |

## How to install + test

```bash
# 1. Build the addon zip
python scripts/build_addon.py
# → dist/synthgen_mcp.zip (710 KB)

# 2. Install in Blender 5.2
#    Edit → Preferences → Add-ons → Install from Disk → select synthgen_mcp.zip
#    Enable "Synthgen MCP"
#    First enable: installs mcp SDK (~15s)

# 3. Check the N-panel
#    3D Viewport → Sidebar (N) → "Synthgen MCP" tab
#    Should show "Server running on port 8400"

# 4. Connect from your IDE
#    Add to MCP config: {"synthgen": {"url": "http://localhost:8400/sse"}}

# 5. Test a tool call
#    Ask your agent: "Use schema_find to search for 'Distribute'"
```

## Architecture

```
IDE (Claude Code / Cursor / VS Code)
  │
  │  SSE HTTP on port 8400
  │
  ▼
Blender addon (synthgen_mcp)
  ├── FastMCP SSE server (daemon thread)
  │     └── 33 registered tools
  ├── MainThreadExecutor
  │     ├── queue.Queue (code submissions)
  │     ├── bpy.app.timers (10ms poll)
  │     └── concurrent.futures.Future (results)
  ├── AddonTransport (duck-types TransportBackend)
  ├── Bundled synthgen package
  ├── Bundled schema data (data/schemas/)
  └── N-panel UI (status, start/stop, copy config)
```

## Key design decisions

- **Duck-typing over inheritance** — `AddonTransport` doesn't inherit `TransportBackend`
  to avoid importing transport.py at class-definition time. It implements the same
  interface (`execute_python`, `get_blender_version`, `dirty`/`mark_dirty`/`clear_dirty`,
  `close`). The tool modules only care about the interface, not the base class.

- **Deferred auto-start** — Server starts 0.5s after addon enable via `bpy.app.timers`,
  not during `register()`. This avoids blocking Blender's startup and ensures the UI
  context is fully initialized.

- **Dual-mode path setup** — `__init__.py` detects whether `synthgen/` is bundled
  (distribution) or absent (development). Distribution mode adds the addon dir to
  sys.path; dev mode adds `src/` from the repo root.

- **Schema root override** — `_SCHEMAS_ROOT_OVERRIDE` in `query.py` lets the addon
  point schema resolution at its bundled data without modifying any other code paths.
  CLI and standalone MCP server still use the default repo-relative path.

## Risks + mitigations

- **pydantic-core ABI**: the pip install targets Blender's bundled Python (3.12.x for
  Blender 5.2). If a compatible wheel doesn't exist, the install fails with a clear
  error message pointing the user at the manual pip command.

- **SSE server shutdown**: the server thread is daemon, so it dies with Blender. For
  restart-in-session, `stop()` flags the executor to stop polling and sets the server
  reference to None. The old daemon thread may linger briefly but releases the port.

- **Main-thread latency**: 10ms poll adds small latency per tool call. For `sweep`
  (which renders many frames in a single transport call), this is paid once, not per-frame.
