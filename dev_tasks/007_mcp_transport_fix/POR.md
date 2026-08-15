# POR — MCP transport fix (SSE → streamable-http)

## Problem

Claude Code cannot call any of the 43 synthgen MCP tools. Every call
fails with:

```
MCP error -32602: Invalid request parameters
```

This is a **complete blocker** for live validation of the toolset.
Dev_task 006 implemented 7 hardening fixes (315 tests passing), but none
can be tested against a live Blender instance through the MCP.

## Root cause — confirmed

The Blender system console reveals the actual server-side error
(logged by `mcp/shared/session.py:383`):

```
WARNING  Failed to validate request: Received request before initialization was complete
```

Claude Code connects to the SSE endpoint and sends `tools/call` requests
on sessions that **never completed the MCP `initialize` handshake**.
The server log shows zero `InitializeRequest` entries from Claude Code —
it jumps straight to `tools/call`.

Critically, Claude Code *does* discover the tools (ToolSearch lists all
43 tools and the server instructions appear in context). This suggests
it connects and initializes successfully on one session for tool
discovery, but uses a different un-initialized session for actual calls.

## Current state

### Server transport

**File:** `addon/synthgen_mcp/server.py:100`

```python
mcp.run(transport="sse")
```

This starts the **legacy SSE transport** (`GET /sse` → server sends
`endpoint` event with `/messages?session_id=...` POST URL → client
POSTs JSON-RPC to that URL). The MCP spec has deprecated this in favor
of `streamable-http`.

The `FastMCP.run()` method accepts three transport values:

```python
transport: Literal['stdio', 'sse', 'streamable-http']
```

### Client config

**File:** `~/.claude.json` (user-global, the authoritative config):

```json
{
  "mcpServers": {
    "synthgen": {
      "type": "sse",
      "url": "http://localhost:8400/sse"
    }
  }
}
```

**File:** `.claude/mcp_servers.json` (project-level, possibly ignored):

```json
{
  "synthgen": {
    "type": "sse",
    "url": "http://localhost:8400/sse"
  }
}
```

Note: there is no `.mcp.json` at the repo root (the standard location
for project-scoped MCP config).

### SDK versions

Both host and vendored addon use `mcp==1.29.0`. The vendored copy is at
`Blender/5.2/scripts/addons/synthgen_mcp/vendor/mcp-1.29.0.dist-info`.

### What works

- `python tools/validate_addon.py` — hand-rolled JSON-RPC client that
  does the full `initialize` → `notifications/initialized` → `tools/list`
  → `tools/call` handshake on a single SSE session. **Always passes.**
- Direct Python `mcp` SDK client connecting to `http://localhost:8400/sse`
  and calling `schema_find({"substring": "distribute"})`. **Works.**
- `ToolSearch` from Claude Code — discovers all 43 tools and the server
  instructions appear in the agent's context.

### What fails

- Every `mcp__synthgen__*` tool call from Claude Code.

## Things tried

1. Added `"type": "sse"` to `.claude/mcp_servers.json` — no change.
2. Verified SDK versions match (both 1.29.0) — not a version mismatch.
3. Checked `extra="allow"` on pydantic models — the SDK is permissive
   about extra fields, ruling out "unknown field" as the cause.
4. Confirmed the error is NOT about tool parameter schemas — the
   `schema_find` tool works with the exact same parameters from other
   clients.

## Decisions locked

- The fix must not break `validate_addon.py` or direct SDK client usage.
- The `/health` endpoint must continue working (used by deploy/validate).
- Tool registration and code-gen are unchanged — this is transport-only.
- 315 tests must remain green (they don't touch the transport layer).

## Strategy

### Minimal reproduction

Before fixing, confirm the diagnosis with a controlled test:

1. Start Blender with system console visible (Window → Toggle System
   Console, or launch from terminal).
2. From Claude Code, trigger any MCP tool call (e.g. via ToolSearch →
   call `schema_find`).
3. Observe the server console: expect `"Received request before
   initialization was complete"` with no preceding `InitializeRequest`.

### Fix approach: switch to streamable-http

The most likely fix is switching the server transport from `sse` to
`streamable-http`. This is a one-line change on the server side, plus
a client config update.

#### Step 1 — Switch server transport

**File:** `addon/synthgen_mcp/server.py:100`

```python
# Before:
mcp.run(transport="sse")

# After:
mcp.run(transport="streamable-http")
```

The `streamable-http` transport uses a single HTTP POST endpoint
(`/mcp` by default) for all JSON-RPC messages. No SSE session
management needed — each request/response is a standard HTTP
round-trip, with optional SSE streaming for long-running responses.

**Investigate first:** What is the default mount path for
`streamable-http`? Is it `/mcp`? Does the `/health` custom route
still work? The `@mcp.custom_route("/health")` decorator is
Starlette-based and should survive a transport change, but verify.

#### Step 2 — Update client config

**File:** `~/.claude.json` — update the synthgen entry:

```json
{
  "mcpServers": {
    "synthgen": {
      "type": "http",
      "url": "http://localhost:8400/mcp"
    }
  }
}
```

Claude Code docs say `"http"` and `"streamable-http"` are functionally
identical on the client side. The URL changes from `/sse` to `/mcp`
(or whatever the streamable-http mount path is).

Also create `.mcp.json` at the repo root (the standard project-level
config location) so other users don't need manual setup:

```json
{
  "mcpServers": {
    "synthgen": {
      "type": "http",
      "url": "http://localhost:8400/mcp"
    }
  }
}
```

#### Step 3 — Update validate_addon.py

The validate script currently does a manual SSE handshake (lines
120-230). It needs to switch to the streamable-http protocol:
- POST JSON-RPC directly to `http://localhost:8400/mcp`
- Parse the response as JSON (not SSE events)
- The `initialize` → `tools/list` → `tools/call` sequence is the
  same, but the transport is synchronous HTTP, not SSE event streams.

**Alternatively**, keep the validate script working against both
transports if backwards compatibility is needed, or just switch it
since SSE is being removed.

#### Step 4 — Update deploy_addon.py and docs

The deploy script references the SSE endpoint in its output messages.
Update any hardcoded URLs or transport references.

#### Step 5 — Verify

1. `python tools/deploy_addon.py` — deploy the updated addon.
2. Open Blender (addon auto-starts the new transport).
3. `python tools/validate_addon.py` — confirm health + tool calls work.
4. From Claude Code, call `mcp__synthgen__schema_find` — confirm it
   returns results instead of -32602.
5. Run a multi-tool sequence to exercise the full pipeline.

### Fallback: dual transport

If `streamable-http` breaks something (e.g. the `/health` custom route,
or the Starlette/Uvicorn middleware chain), consider running both:

```python
# Mount streamable-http as primary
app = mcp.streamable_http_app()
# Mount legacy SSE as fallback
app.mount("/sse", mcp.sse_app())
```

This would let `validate_addon.py` keep working via SSE while Claude
Code uses streamable-http. Check if `FastMCP` exposes these app
factories.

### Alternative: fix the SSE client

If switching transports is too invasive, the other approach is to
investigate why Claude Code's SSE client doesn't complete the
handshake. This is a Claude Code client-side issue and may not be
fixable from our side. The `streamable-http` switch is the more
actionable path.

## Key files

| File | Role |
|------|------|
| `addon/synthgen_mcp/server.py` | MCP server lifecycle, transport config |
| `addon/synthgen_mcp/deps.py` | Dependency management (`mcp[cli]>=1.3.0,<2`) |
| `addon/synthgen_mcp/executor.py` | Transport layer, `MainThreadExecutor` |
| `tools/validate_addon.py` | Health + SSE + MCP tool call validation |
| `tools/deploy_addon.py` | Addon deployment script |
| `~/.claude.json` | User-global Claude Code config (has synthgen MCP entry) |
| `.claude/mcp_servers.json` | Project-level MCP config (may be redundant) |

## Deploy + validate

```bash
python tools/deploy_addon.py       # kills Blender, copies addon + src
python tools/validate_addon.py     # health, transport, MCP tool call
```

After transport fix, also test from Claude Code:
```
# In Claude Code, call any synthgen tool:
mcp__synthgen__schema_find(substring="distribute")
```

## Risk assessment

**Low risk.** This is a transport-layer change only. No tool code, no
code-gen logic, no test infrastructure is affected. The 315 existing
tests don't touch the transport and will remain green.

The main risk is that `streamable-http` may behave differently with
Starlette/Uvicorn middleware (custom routes, CORS, etc.). Test the
`/health` endpoint and a full tool call sequence after the switch.
