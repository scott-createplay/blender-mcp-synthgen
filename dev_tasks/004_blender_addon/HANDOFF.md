# Handoff — Blender Addon (dev_task 004)

## Where we are

This task has not started. The POR is written and ready for implementation.

## What exists today

The synthgen MCP server (`src/synthgen/mcp/server.py`) works as a standalone stdio
process with 33 registered tools and 175 passing offline tests. It connects to Blender
via an external TCP addon (ahujasid/blender-mcp on port 9876). This works but requires
the user to:

1. Install the external addon separately
2. Run Claude Code from the synthgen project directory
3. Manually start the socket server in Blender

**This task replaces that with a single self-contained Blender addon.**

## What needs to be built

A Blender addon (`addon/synthgen_mcp/`) that:

1. Bundles the entire synthgen package + schema data
2. Runs an SSE MCP server on a local port (default 8400) inside Blender
3. Marshals all bpy calls to the main thread via `bpy.app.timers`
4. Provides an N-panel UI showing server status and config
5. Installs its own dependencies (mcp SDK) on first enable

The user experience becomes: install addon zip → enable → copy MCP config into
Claude Code → done.

## Architecture summary

```
Claude Code ──(SSE HTTP on port 8400)──► Blender addon
  │                                        │
  │  JSON-RPC / MCP protocol               ├── FastMCP SSE server (background thread)
  │                                        ├── MainThreadExecutor (bpy.app.timers queue)
  │                                        ├── AddonTransport (TransportBackend)
  │                                        ├── 33 tools (schema/graph/blender/pipeline/verify)
  │                                        ├── Grounding validation (schema data bundled)
  │                                        └── N-panel UI
```

Key constraint: bpy is main-thread-only. The SSE server runs in a daemon thread.
A `MainThreadExecutor` queues code execution requests and a `bpy.app.timers` callback
polls the queue every 10ms, executing code on the main thread and returning results
via `concurrent.futures.Future`.

## Files to read before starting

- `dev_tasks/004_blender_addon/POR.md` — full plan with stages and validation checkboxes
- `src/synthgen/mcp/transport.py` — existing transport backends (reuse `TransportBackend` base)
- `src/synthgen/mcp/server.py` — tool registration pattern
- `dev_tasks/003_mcp_stabilize_and_ground/HANDOFF.md` — what the 33 tools do
- `knowledge/procedural_paradigm.md` — the "derive, don't set" philosophy

## Key risks

1. **pydantic-core ABI** — compiled binary must match Blender's Python exactly
2. **SSE server shutdown** — need clean stop/restart without port conflicts
3. **Main-thread latency** — 10ms poll interval adds small latency per tool call
4. **sys.path management** — vendored deps must not conflict with Blender's packages

## How to test

```bash
# Offline tests still work (no Blender needed)
pip install -e ".[dev]" && pytest

# Build the addon zip
python scripts/build_addon.py

# Install in Blender
# 1. Edit → Preferences → Add-ons → Install → select synthgen_mcp.zip
# 2. Enable "Synthgen MCP"
# 3. Wait for dependencies to install (first time only)
# 4. Check N-panel → Synthgen MCP → "Server running on port 8400"

# Connect Claude Code
# Add to your MCP config:
# {"synthgen": {"url": "http://localhost:8400/sse"}}
```
