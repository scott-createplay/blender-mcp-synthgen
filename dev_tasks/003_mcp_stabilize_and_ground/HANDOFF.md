# Handoff — MCP Stabilization & Grounding (dev_task 003)

## Where we are

Stages 1–4 of the `003_mcp_stabilize_and_ground` POR are **complete**. The MCP server
is stable, returns structured JSON, validates identifiers against the schema before
they reach Blender, reconnects after transport failures, and has a full procedural
authoring toolset with dirty-flag invalidation. 113 offline tests pass. 25 tools are
registered.

## What was built in this task

### Stage 1 — Transport stabilization
- **`TransportError` exception** with clear, actionable messages ("is the BlenderMCP
  addon started?") including host:port and troubleshooting steps.
- **Reconnection logic** — `SocketTransport` now closes dead sockets and reconnects
  automatically on the next call. Separate `connect_timeout` (5s default) vs command
  timeout (180s).
- **Structured JSON responses** — all 4 schema tools now return parsed JSON
  (`{"results": [...], "count": N}` or `{"node": {...}}`) instead of captured CLI
  stdout. New `data_find`, `data_show`, `data_socket`, `data_setting` functions in
  `schema/query.py` return data directly.
- **Standardized graph preamble** — all 6 graph tools share a single `_PREAMBLE`
  constant for `sys.path` injection. Same-machine assumption documented.

### Stage 2 — Phase 3a completion
- **Version-aware schema resolution** — `resolve_schema_dir((5, 2, 0))` maps to
  `"blender-5.2"` with closest-match fallback. Server detects Blender version on first
  transport connection and propagates to schema + blender tools. `load_schema()` accepts
  optional `blender_dir` parameter. CLI still works with hardcoded default.
- **`verify_attribute_exists` tool** — cooks depsgraph, checks evaluated mesh attributes,
  returns `{exists, domain, data_type}` or `{exists: false, available: [...]}`. Registered
  in server.py.

### Stage 3 — Grounding enforcement
- **`grounding.py` module** with three validators:
  - `validate_node_type(node_type, tree_type)` — checks against schema
  - `validate_socket(node_type, socket_id, tree_type, is_input)` — catches label-vs-identifier mistakes
  - `validate_setting(node_type, setting_name, tree_type)` — validates enum settings
  - All return `ValidationResult(valid, canonical, suggestions, message)` with fuzzy
    "did you mean?" via `difflib.get_close_matches`.
- **Wired into Layer 2 tools:**
  - `add_node` — always validates `node_type` before sending code to Blender
  - `set_node_property` — validates when optional `node_type` parameter is provided
  - `set_socket_default` — validates when optional `node_type` parameter is provided
  - `link_sockets` — NOT statically validated (uses instance names, not type IDs;
    Blender-side validation with good error messages is the fallback)

### Stage 4 — Procedural authoring tools + dirty-flag
- **`expose_parameter` tool** — adds sockets to GN group interfaces via
  `tree.interface.new_socket()`. Supports default/min/max values, INPUT/OUTPUT.
- **`add_driver` tool** — adds scripted driver expressions to object properties.
  Supports variable definitions with proper `bpy.data.<collection>` resolution via
  lookup table. Variables reference other objects/materials/scenes by id_type + id_name.
- **`wire_attr_bridge` compound tool** — creates Store Named Attribute (GN writer) +
  Attribute node (shader reader) in one call. Enforces the three alignment rules from
  `knowledge/attribute_bridge.md`: `data_type` set before linking Value socket,
  `attribute_name` set as node property (not socket), and shader output mapped correctly
  (FLOAT→Fac, FLOAT_COLOR→Color, FLOAT_VECTOR→Vector). Both node types grounding-validated.
- **`wire_compositor_pass` tool** — creates Render Layers + File Output nodes in the
  compositor, linked on the specified pass. Uses `scene.compositing_node_group`
  (Blender 5.x API). Both compositor node types grounding-validated.
- **Dirty-flag invalidation** — `TransportBackend` gains `dirty`/`mark_dirty()`/
  `clear_dirty()`. All mutating tools (`_run(..., mutates=True)`) set the flag.
  Graph tools auto-inject `g.resolve_attr_bridges()` via `_graph_preamble()` when
  dirty. `graph_attribute_trace` always resolves regardless of flag state.

## Files changed (read these)

### New files
| File | What |
|---|---|
| `src/synthgen/mcp/grounding.py` | Schema validation — `validate_node_type`, `validate_socket`, `validate_setting` |
| `src/synthgen/mcp/tools/verify.py` | `verify_attribute_exists` tool |
| `tests/test_transport.py` | Transport reconnection + error handling tests |
| `tests/test_mcp_schema.py` | Structured JSON response tests + MCP tool integration |
| `tests/test_mcp_graph.py` | Preamble consistency tests |
| `tests/test_grounding.py` | Grounding validation + Layer 2 integration tests |
| `tests/test_stage4_tools.py` | Stage 4 tools + dirty-flag tests (40 tests) |

### Modified files
| File | What changed |
|---|---|
| `src/synthgen/mcp/transport.py` | `TransportError`, `_close_socket()`, reconnect-on-failure, `connect_timeout`, dirty-flag (`dirty`/`mark_dirty`/`clear_dirty`) on `TransportBackend` |
| `src/synthgen/mcp/server.py` | `_blender_dir` detection on first connect, `verify_tools` registered, `_get_blender_dir` passed to schema + blender tools |
| `src/synthgen/mcp/tools/schema.py` | Returns JSON via `data_*` functions, accepts `get_blender_dir` callback |
| `src/synthgen/mcp/tools/graph.py` | `_graph_preamble()` with auto-resolve when dirty, all 6 tools refactored to use it |
| `src/synthgen/mcp/tools/blender.py` | Grounding validators imported; `_run(mutates=True)` on all mutating tools; Stage 4 tools added: `expose_parameter`, `add_driver`, `wire_attr_bridge`, `wire_compositor_pass` |
| `src/synthgen/schema/query.py` | `resolve_schema_dir()`, `data_find/show/socket/setting()`, `load_schema(blender_dir=)` |
| `tests/test_schema_query.py` | Added `TestVersionResolution` class |

## What's NOT done (POR Stages 5–6)

### Stage 5 — Phase 3c (setup + sweep)
- [ ] **Layer 1 gaps:** `edit_mesh`, `import_asset`, `configure_render`, `add_keyframes`
- [ ] **Layer 4 entirely:** `set_parameter`, `render`, `sweep`, `export_labels`
- [ ] **Provenance snapshots** — auto-save graph state with render/sweep outputs
- [ ] **Agent guidance** in all tool descriptions (procedural-first nudges)

### Stage 6 — Housekeeping
- [ ] **Update ROADMAP.md** — Phase 3 in progress, POR decisions locked
- [ ] **Reconcile file layout** — document `blender.py` consolidation vs POR's split

## Architecture notes for the next agent

### Grounding asymmetry
`add_node` **always** validates (it knows the type ID), but `link_sockets`,
`set_node_property`, and `set_socket_default` work with node **instance names**
(the `.name` property in the tree), not type IDs. Static validation only happens
when the caller passes the optional `node_type` parameter. Blender-side error
messages (which list available sockets/properties) are the fallback.

### Dirty-flag design
The dirty flag lives on `TransportBackend` (shared by `SocketTransport` and
`DirectBpyTransport`). It's a global bool — "something mutated, re-resolve
everything." This matches the `scene_graph_contexts.md` guidance: "memoize within
a graph session keyed on the depsgraph update tag; invalidate on scene change."
Per-object scoping was considered but deferred as unnecessary complexity.

### Compound tools pattern
`wire_attr_bridge` and `wire_compositor_pass` are the first multi-node compound
tools. They generate a single Python script that creates multiple nodes, sets
properties, and links sockets in one `execute_python` call. The response JSON
includes all created node names/identifiers so the agent can reference them in
subsequent tool calls.

### Layer 4 guidance
`set_parameter` should set GN modifier socket values via
`obj.modifiers["name"]["Socket_N"]`. `render` should call `bpy.ops.render.render()`
with configurable output path. `sweep` iterates parameter combinations and renders
each. `export_labels` extracts ground-truth data from compositor File Output nodes
or attribute values.

## How to test

```bash
# All tests (no Blender needed)
pip install -e ".[dev]" && pytest

# Quick schema tool smoke test
python -c "
from synthgen.schema.query import data_find, load_schema
nodes = load_schema('gn')[0]['nodes']
print(data_find(nodes, 'Distribute'))
"

# Quick grounding test
python -c "
from synthgen.mcp.grounding import validate_node_type
print(validate_node_type('GeometryNodeDistributePointsOnFace', 'gn'))
"

# Interactive test (requires Blender + BlenderMCP addon on port 9876)
# 1. Start Blender, enable BlenderMCP addon, click Start Server
# 2. Run: python -m synthgen.mcp.server
# 3. Connect from Claude Code or Cursor via .claude/mcp_servers.json
```

## Key context
- Read `dev_tasks/003_mcp_stabilize_and_ground/POR.md` for the full plan with checkboxes
- Read `dev_tasks/002_mcp_layer/HANDOFF.md` for the original MCP layer context
- Read `knowledge/attribute_bridge.md` before modifying `wire_attr_bridge`
- Read `knowledge/procedural_paradigm.md` for the "derive, don't set" philosophy
- Blender 5.x removed `scene.node_tree` — compositor is `scene.compositing_node_group`
