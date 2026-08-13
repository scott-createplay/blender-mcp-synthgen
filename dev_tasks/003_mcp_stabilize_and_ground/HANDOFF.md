# Handoff — MCP Stabilization & Grounding (dev_task 003)

## Where we are

Stages 1–3 of the `003_mcp_stabilize_and_ground` POR are **complete**. The MCP server
is now stable, returns structured JSON, validates identifiers against the schema before
they reach Blender, and reconnects gracefully after transport failures. 73 offline tests
pass (up from 18). 21 tools are registered (up from 20).

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

### Modified files
| File | What changed |
|---|---|
| `src/synthgen/mcp/transport.py` | `TransportError`, `_close_socket()`, reconnect-on-failure in `_send_command`, `connect_timeout` param |
| `src/synthgen/mcp/server.py` | `_blender_dir` detection on first connect, `verify_tools` registered, `_get_blender_dir` passed to schema + blender tools |
| `src/synthgen/mcp/tools/schema.py` | Returns JSON via `data_*` functions, accepts `get_blender_dir` callback, `_load_nodes` moved inside `register()` |
| `src/synthgen/mcp/tools/graph.py` | `_PREAMBLE` constant, `_src_path()` moved to module level, all 6 tools use same preamble |
| `src/synthgen/mcp/tools/blender.py` | Imports grounding validators, `add_node`/`set_node_property`/`set_socket_default` validate before sending |
| `src/synthgen/schema/query.py` | `resolve_schema_dir()`, `data_find/show/socket/setting()`, `load_schema(blender_dir=)` param |
| `tests/test_schema_query.py` | Added `TestVersionResolution` class |

## What's NOT done (POR Stages 4–6)

### Stage 4 — Complete Phase 3b (procedural authoring)
- [ ] **`expose_parameter` tool** — add socket to GN group interface
- [ ] **`add_driver` tool** — add driver expressions
- [ ] **`wire_attr_bridge` helper** — compound Store Named Attribute + Attribute node,
      type-checked. See `knowledge/attribute_bridge.md` for spec.
- [ ] **`wire_compositor_pass` helper** — render pass → File Output, must use
      `scene.compositing_node_group` (Blender 5.x)
- [ ] **Dirty-flag invalidation** — Layer 2 mutations set a flag → next Layer 3 query
      auto-resolves tier-2 edges

### Stage 5 — Phase 3c (setup + sweep)
- [ ] **Layer 1 gaps:** `edit_mesh`, `import_asset`, `configure_render`, `add_keyframes`
- [ ] **Layer 4 entirely:** `set_parameter`, `render`, `sweep`, `export_labels`
- [ ] **Provenance snapshots** — auto-save graph state with render/sweep outputs
- [ ] **Agent guidance** in all tool descriptions (procedural-first nudges)

### Stage 6 — Housekeeping
- [ ] **Update ROADMAP.md** — Phase 3 in progress, POR decisions locked
- [ ] **Reconcile file layout** — document `blender.py` consolidation vs POR's split

## Architecture notes for the next agent

The grounding design has a deliberate asymmetry: `add_node` **always** validates
(it knows the type ID), but `link_sockets`, `set_node_property`, and `set_socket_default`
work with node **instance names** (the `.name` property in the tree), not type IDs.
Static validation only happens when the caller passes the optional `node_type` parameter.
Blender-side error messages (which list available sockets/properties) are the fallback.

For `link_sockets`, a future improvement could be to first query Blender for the node's
`bl_idname`, then validate the socket against the schema — but that doubles the round
trips. The current Blender-side error messages are already good.

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
```

## Key context
- Read `dev_tasks/003_mcp_stabilize_and_ground/POR.md` for the full plan with checkboxes
- Read `dev_tasks/002_mcp_layer/HANDOFF.md` for the original MCP layer context
- Read `knowledge/attribute_bridge.md` before implementing `wire_attr_bridge`
- Read `knowledge/procedural_paradigm.md` for the "derive, don't set" philosophy
- Blender 5.x removed `scene.node_tree` — compositor is `scene.compositing_node_group`
