# POR — MCP Stabilization & Grounding (Phase 3 cont.)

## Goal

Complete the Phase 3 MCP layer by stabilizing what's built (transport resilience,
structured responses, error clarity), filling the Phase 3a gaps (version-aware schema,
`verify.attribute_exists`, integration tests), and implementing grounding enforcement —
the POR's "non-negotiable" requirement that hallucinated node/socket identifiers are
rejected at the MCP boundary before they reach bpy.

This plan picks up from `dev_tasks/002_mcp_layer/HANDOFF.md`. The server skeleton works,
20 tools are registered, 18 offline tests pass. The focus now shifts from "does it exist"
to "does it work reliably and correctly."

## Stages

### Stage 1 — Stabilize (smoke-test readiness)

Minimum fixes to get a reliable first interactive test with Blender.

#### 1.1 Fix SocketTransport reconnection

**Problem:** `SocketTransport._connect()` checks `if self._sock is not None` and reuses
a dead socket rather than reconnecting. If Blender restarts, the MCP server is stuck.

**Fix:** On connection failure or send error, close the socket, set `self._sock = None`,
and reconnect on the next call. Add a configurable connection timeout (default 5s) so
first-connect fails fast instead of hanging.

**Files:** `src/synthgen/mcp/transport.py`

**Validation:**
- [x] Unit test: mock socket that dies mid-session, verify reconnect succeeds
- [x] Unit test: connection to unreachable host times out within 5s
- [x] Existing 18 tests still pass

#### 1.2 Transport error clarity

**Problem:** When the ahujasid addon isn't running, the transport hangs or gives an
opaque `ConnectionRefusedError`. The agent (or user) gets no actionable feedback.

**Fix:** Catch `ConnectionRefusedError` and `TimeoutError` in `_connect()` and raise a
`TransportError` with a clear message: "Cannot connect to Blender on {host}:{port} — is
the BlenderMCP addon started? (N panel → BlenderMCP → Start Server)". Add a
`TransportError` exception class.

**Files:** `src/synthgen/mcp/transport.py`

**Validation:**
- [x] Unit test: connection refused → `TransportError` with helpful message
- [x] Unit test: timeout → `TransportError` with helpful message

#### 1.3 Structured JSON responses for schema tools

**Problem:** Schema tools capture CLI stdout (human-readable text) and return raw strings.
Other tools return JSON. Inconsistent.

**Fix:** Schema tools return structured JSON: `{"results": [...]}` for `schema_find` /
`schema_socket` / `schema_setting`, `{"node": {...}}` for `schema_show`. Parse the
schema data directly instead of capturing CLI stdout.

**Files:** `src/synthgen/mcp/tools/schema.py`, `src/synthgen/schema/query.py` (expose
data-returning variants of the CLI functions if needed)

**Validation:**
- [x] Unit test: each schema tool returns valid JSON with expected structure
- [x] Existing schema CLI still works unchanged

#### 1.4 Standardize sys.path injection in graph tools

**Problem:** `graph_nodes()` uses a different `sys.path` pattern than the other 5 graph
tools. The `_src_path()` helper embeds the MCP-server-side path into Blender-side code,
which only works on the same machine (fine for now, but fragile).

**Fix:** Standardize all 6 graph tools to use the same `_src_path()` pattern. Extract a
`_preamble()` helper that returns the `sys.path.insert` + common imports as a string
fragment. Document the same-machine assumption.

**Files:** `src/synthgen/mcp/tools/graph.py`

**Validation:**
- [x] All 6 graph tool code strings start with identical preamble
- [x] Existing tests pass

---

### Stage 2 — Complete Phase 3a (read-only introspection)

#### 2.1 Version-aware schema resolution

**Problem:** `schema/query.py` hardcodes `BLENDER_DIR = "blender-5.2"`. The POR requires
dynamic resolution from `bpy.app.version`.

**Fix:**
1. Add a `resolve_schema_dir(version: tuple[int,int,int]) -> str` function to
   `schema/query.py` that maps `(5, 2, 0)` → `"blender-5.2"`, with fallback to the
   closest available version directory.
2. On MCP server startup (first transport connection), query `transport.get_blender_version()`,
   resolve the schema dir, and pass it to schema tools.
3. Schema tools accept an optional `schema_dir` override; default falls back to the
   hardcoded value for CLI use.
4. `load_schema()` accepts an optional `blender_dir` parameter.

**Files:** `src/synthgen/schema/query.py`, `src/synthgen/mcp/server.py`,
`src/synthgen/mcp/tools/schema.py`

**Validation:**
- [x] Unit test: `resolve_schema_dir` returns correct dir for known versions
- [x] Unit test: `resolve_schema_dir` falls back gracefully for unknown versions
- [x] Schema tools work with explicit dir override
- [x] CLI still works with default hardcoded dir

#### 2.2 `verify.attribute_exists` tool

**Problem:** POR Phase 3a deliverable, not implemented. Should cook depsgraph and confirm
a named attribute exists on an evaluated object.

**Fix:** New tool in a new file `src/synthgen/mcp/tools/verify.py`. The tool takes
`object_name` and `attribute_name`, generates Python code that:
1. Gets the object from `bpy.data.objects`
2. Gets the evaluated object from `depsgraph.object_get_evaluated(obj)`
3. Checks `attribute_name in [a.name for a in eval_obj.data.attributes]`
4. Returns `{"exists": bool, "domain": str, "data_type": str}` if found

Register in `server.py`.

**Files:** `src/synthgen/mcp/tools/verify.py`, `src/synthgen/mcp/server.py`

**Validation:**
- [x] Tool registered and callable
- [x] Code generation produces valid Python for Blender execution

#### 2.3 MCP integration tests (schema tools)

**Problem:** No tests exercise the MCP protocol layer. Schema tools can be tested without
Blender since they only read local JSON files.

**Fix:** Add integration tests that call schema tools through the MCP server interface
(or at minimum, through their registered function signatures with mocked FastMCP context).

**Files:** `tests/test_mcp_schema.py`

**Validation:**
- [ ] Tests cover all 4 schema tools
- [ ] Tests verify JSON structure of responses
- [ ] Tests verify error cases (unknown node type, bad tree_type)

---

### Stage 3 — Grounding enforcement

#### 3.1 Build `grounding.py`

**Problem:** The POR's "non-negotiable" requirement. Layer 2 tools currently pass
node/socket identifiers straight to Blender. Hallucinated identifiers should be rejected
at the MCP boundary with "did you mean?" suggestions.

**Fix:** New module `src/synthgen/mcp/grounding.py` with:
- `validate_node_type(node_type, tree_type) -> ValidationResult` — checks against schema
- `validate_socket(node_type, socket_id, tree_type, is_input) -> ValidationResult`
- `validate_setting(node_type, setting_name, tree_type) -> ValidationResult`
- `ValidationResult` dataclass: `valid: bool`, `canonical: str | None`,
  `suggestions: list[str]`, `message: str`
- Fuzzy matching via `difflib.get_close_matches` for suggestions

**Files:** `src/synthgen/mcp/grounding.py`

**Validation:**
- [x] Unit test: valid identifiers pass through
- [x] Unit test: close misspellings return suggestions
- [x] Unit test: completely wrong identifiers return "not found" with no suggestions
- [x] Unit test: validation works for all three tree types (gn, shader, compositor)

#### 3.2 Wire grounding into Layer 2 tools

**Problem:** `add_node`, `link_sockets`, `set_node_property`, `set_socket_default` do no
validation before sending code to Blender.

**Fix:** Each Layer 2 tool calls the appropriate grounding function before generating
code. If validation fails, the tool returns the error message (with suggestions)
immediately — no code is sent to Blender.

**Files:** `src/synthgen/mcp/tools/blender.py`, `src/synthgen/mcp/grounding.py`

**Validation:**
- [x] Unit test: `add_node` with invalid node type returns grounding error
- [x] Unit test: `set_socket_default` with invalid socket id returns grounding error with suggestions
- [x] Unit test: valid identifiers still pass through and generate code
- [x] Existing tests still pass

---

### Stage 4 — Complete Phase 3b (procedural authoring)

#### 4.1 `expose_parameter` tool

Add socket to GN group interface for external parameter control.

**Files:** `src/synthgen/mcp/tools/blender.py`

#### 4.2 `add_driver` tool

Add driver expressions linking properties across objects/modifiers.

**Files:** `src/synthgen/mcp/tools/blender.py`

#### 4.3 `wire_attr_bridge` helper

Compound tool: create Store Named Attribute + Attribute node pair, type-checked against
schema. Implements the tier-2 bridge from `knowledge/attribute_bridge.md`.

**Files:** `src/synthgen/mcp/tools/blender.py`

#### 4.4 `wire_compositor_pass` helper

Render pass → File Output using `scene.compositing_node_group` (Blender 5.x API).

**Files:** `src/synthgen/mcp/tools/blender.py`

#### 4.5 Dirty-flag invalidation

Layer 2 mutations set a flag; next Layer 3 query auto-resolves tier-2 edges.

**Files:** `src/synthgen/mcp/transport.py` or `src/synthgen/mcp/server.py`,
`src/synthgen/mcp/tools/blender.py`, `src/synthgen/mcp/tools/graph.py`

---

### Stage 5 — Phase 3c (setup + sweep)

#### 5.1 Remaining Layer 1 tools

`edit_mesh`, `import_asset`, `configure_render`, `add_keyframes`.

#### 5.2 Layer 4 tools

`set_parameter`, `render`, `sweep`, `export_labels`.

#### 5.3 Provenance snapshots

`render` and `sweep` auto-save graph state alongside outputs.

#### 5.4 Agent guidance in all tool descriptions

Procedural-first nudges in every tool description, not just `create_object`.

---

### Stage 6 — Housekeeping

#### 6.1 Update ROADMAP.md

Reflect Phase 3 in-progress, POR decisions locked, ahujasid transport chosen.

#### 6.2 Reconcile file layout

Document the `blender.py` consolidation (vs POR's `procedural.py`/`setup.py` split) as
a deliberate simplification. Update POR or add a note.

---

## Definition of done

### Stage 1 ✓
- [x] SocketTransport reconnects after connection loss
- [x] Connection failures produce clear, actionable error messages
- [x] All schema tools return structured JSON
- [x] Graph tools use consistent sys.path preamble
- [x] All existing tests still pass
- [x] New unit tests for transport resilience and schema JSON structure

### Stage 2 ✓
- [x] Schema resolution is dynamic (from `bpy.app.version`)
- [x] `verify.attribute_exists` tool is registered and functional
- [x] MCP integration tests cover schema tools
- [x] `schema/query.py` CLI still works with hardcoded default

### Stage 3 ✓
- [x] `grounding.py` validates node types, sockets, and settings against schema
- [x] Layer 2 tools reject invalid identifiers before sending to Blender
- [x] Near-miss suggestions via fuzzy matching
- [x] All validation tested for gn, shader, and compositor tree types

### Stage 4 ✓
- [x] `expose_parameter`, `add_driver`, `wire_attr_bridge`, `wire_compositor_pass` tools
- [x] Dirty-flag invalidation wired between Layer 2 and Layer 3

### Stage 5
- [ ] Layer 1 complete (7 tools), Layer 4 complete (4 tools)
- [ ] Provenance snapshots on render/sweep

### Stage 6
- [ ] ROADMAP.md updated
- [ ] File layout documented

## Decisions locked

- **Transport:** compose with ahujasid/blender-mcp via SocketTransport (TCP, port 9876)
- **Security:** advisory/tagged, not enforced (per Phase 3 POR)
- **File layout:** `blender.py` consolidates setup + procedural tools (deviation from
  original POR, documented)
- **Grounding:** enforced, not advisory. Invalid identifiers never reach bpy.
- **Schema resolution:** dynamic from `bpy.app.version` with fallback to closest match
