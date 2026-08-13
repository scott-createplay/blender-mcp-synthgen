# Phase 3 Handoff — MCP Layer

## Where we are

The MCP server skeleton is built and loadable. 20 tools are registered. The user is
about to do their **first interactive test** — opening Blender 5.2 with the ahujasid
addon running, connecting Claude Code with the synthgen MCP server, and trying the
tools live. This is a smoke test, not a polished product. Expect bugs.

## What's built (files you should read)

### MCP server
- `src/synthgen/mcp/server.py` — entry point. FastMCP (reference `mcp` SDK), stdio.
  Registers all tools, lazy-inits the transport on first use.
- `src/synthgen/mcp/transport.py` — `TransportBackend` ABC with two impls:
  - `SocketTransport` — TCP socket to ahujasid addon on localhost:9876
  - `DirectBpyTransport` — `exec()` in-process (headless Blender)
  - `auto_detect_transport()` picks based on env vars / bpy importability
- `src/synthgen/mcp/tools/schema.py` — 4 schema query tools (local, no Blender needed).
  Wraps `synthgen.schema.query` functions, captures stdout.
- `src/synthgen/mcp/tools/graph.py` — 6 graph introspection tools (need Blender).
  Generate Python code strings, send through transport, return JSON.
- `src/synthgen/mcp/tools/blender.py` — 10 mutation tools: Layer 1 setup (create_object,
  create_material, assign_material, set_parent) + Layer 2 procedural (add_gn_modifier,
  add_node, link_sockets, set_node_property, set_socket_default) + execute_python escape hatch.

### Config
- `.claude/mcp_servers.json` — MCP server config for Claude Code. Points to
  `python -m synthgen.mcp.server` with cwd set to the repo root.
- `pyproject.toml` — `mcp[cli]>=1.3.0,<2` added as dependency. Console script
  `synthgen-mcp` registered.

### Blender addon
- ahujasid/blender-mcp addon.py installed to:
  `C:\Users\scooter\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\blender_mcp_addon.py`
- User needs to enable it in Blender: Edit → Preferences → Add-ons → search "BlenderMCP" → enable
- Then start the server: 3D viewport → N panel → BlenderMCP tab → Start Server (port 9876)

### Existing infrastructure (from Phase 2)
- `src/synthgen/schema/query.py` — CLI for grounded node lookup. Works, tested.
- `src/synthgen/scenegraph/protocol.py` — `Edge` dataclass, `SceneGraph` protocol.
- `src/synthgen/scenegraph/traverse.py` — `reachable`, `path`, `impact_set`, `attribute_trace`.
- `src/synthgen/scenegraph/backend_bpy.py` — `LiveGraph` (lazy bpy backend, validated in Phase 2).
- `data/schemas/blender-5.2/{gn,shader,compositor}.json` — extracted schemas.
- Tests: 18 passing (`pytest`), all offline (no Blender needed).

## What's NOT done yet (POR gaps)

Read `dev_tasks/002_mcp_layer/POR.md` for the full spec. The POR defines three
sub-phases (3a, 3b, 3c). Here's what's missing from each:

### Phase 3a gaps (read-only introspection)
- [ ] **Version-aware schema resolution.** `schema/query.py` still hardcodes
      `BLENDER_DIR = "blender-5.2"`. Needs to auto-detect from `bpy.app.version`
      via the transport, with a fallback chain. See POR § "Version-aware schema resolution".
- [ ] **`verify.attribute_exists` tool.** Not implemented yet. Should cook depsgraph
      and confirm an attribute exists on an evaluated object.
- [ ] **Graph tools generate raw Python code strings** that include hardcoded
      `sys.path.insert` for the src directory. This works but is fragile — needs a
      cleaner pattern for ensuring synthgen is importable inside Blender's Python.
- [ ] **Structured JSON responses.** Some tools return raw stdout strings, not parsed
      JSON. Should be consistent.
- [ ] **Integration test** via MCP protocol (not just function calls).
- [ ] **No grounding enforcement yet on graph tools.** The schema tools are passthrough
      only — they don't reject bad identifiers, just return "not found" text.

### Phase 3b gaps (procedural authoring)
- [ ] **`expose_parameter` tool** — add socket to GN group interface. Not implemented.
- [ ] **`add_driver` tool** — add driver expressions. Not implemented.
- [ ] **`wire_attr_bridge` helper** — compound tool: Store Named Attribute + Attribute
      node, type-checked against schema. Not implemented.
- [ ] **`wire_compositor_pass` helper** — render pass → File Output. Not implemented.
      Must use `scene.compositing_node_group` (Blender 5.x).
- [ ] **Grounding enforcement (the big one).** Layer 2 tools should validate node_type
      and socket identifiers against the extracted schema BEFORE sending to Blender.
      Currently they just pass through and let Blender error. The POR says: "rejected
      at the MCP boundary with 'did you mean X?' suggestions from the schema."
- [ ] **Dirty-flag invalidation.** Layer 2 mutations should set a flag that triggers
      tier-2 edge re-resolution on the next Layer 3 query. Not wired yet.

### Phase 3c gaps (setup + sweep)
- [ ] **`edit_mesh` tool** — geometry editing (extrude, bevel, loop cut). Not implemented.
- [ ] **`import_asset` tool** — FBX/OBJ/USD import. Not implemented.
- [ ] **`configure_render` tool** — render engine, resolution, passes. Not implemented.
- [ ] **`add_keyframes` tool** — animation data. Not implemented.
- [ ] **Layer 4 tools entirely missing:** `set_parameter`, `render`, `sweep`, `export_labels`.
- [ ] **Provenance snapshots** — `render` and `sweep` should auto-save graph state
      alongside outputs.
- [ ] **Agent guidance in tool descriptions** — partially done (create_object has it),
      but not all Layer 1 tools have procedural-first nudges.

## Known issues / likely failures in first test

1. **Transport might fail silently.** If the ahujasid addon isn't started in Blender,
   `SocketTransport` will hang or error on the first tool call. The auto-detect
   defaults to SocketTransport when neither env vars nor bpy are available — which is
   the normal Claude Code case. Error messages could be clearer.

2. **Graph tools assume synthgen is on sys.path inside Blender.** They inject
   `sys.path.insert(0, r'{_src_path()}')` into the code they send to Blender.
   This only works if the MCP server runs from the repo directory. If Blender's
   Python can't find synthgen, graph tools will fail.

3. **ahujasid addon might not work with Blender 5.2.** It claims min version 3.0 and
   has no 5.x-specific code. Likely works but unverified. The socket server refusing
   to start in headless mode is by design (not a bug).

4. **No connection lifecycle management.** The socket transport connects lazily but
   has no reconnect logic. If Blender restarts, the MCP server needs to restart too.

5. **POR file layout doesn't match implementation.** POR says `mcp/` at repo root with
   `tools/procedural.py`, `tools/setup.py`, `tools/sweep.py`, `tools/verify.py`,
   `grounding.py`. Actual implementation is at `src/synthgen/mcp/` with `tools/blender.py`
   (combining setup + procedural), `tools/graph.py`, `tools/schema.py`. No `grounding.py`
   or `verify.py` yet. Reconcile the POR or reorganize the code — user's call.

## How to test

### Schema tools (no Blender needed)
```
python -c "
from synthgen.mcp.tools.schema import _load_nodes, _capture
from synthgen.schema.query import cmd_show
nodes = _load_nodes('gn')
print(_capture(cmd_show, nodes, 'GeometryNodeDistributePointsOnFaces'))
"
```

### Full MCP via Claude Code
1. Open Blender 5.2
2. Enable BlenderMCP addon (Edit → Preferences → Add-ons)
3. Start the server (N panel → BlenderMCP → Start Server)
4. Restart Claude Code in the project directory (picks up `.claude/mcp_servers.json`)
5. Ask the agent to create an object or query a schema

### Direct transport test (no MCP protocol)
```python
from synthgen.mcp.transport import SocketTransport
t = SocketTransport()  # connects to localhost:9876
print(t.execute_python("import bpy; print(bpy.data.objects.keys())"))
print(t.get_blender_version())
```

## Architecture context

Read these for the full picture (don't duplicate their content):
- `dev_tasks/002_mcp_layer/POR.md` — the full Phase 3 plan with decisions locked
- `docs/ONBOARDING.md` — project context and gotchas
- `knowledge/procedural_paradigm.md` — the "derive, don't set" constitution
- `knowledge/attribute_bridge.md` — tier-2 bridge edge implementation

The core insight: this is not just an MCP wrapper around bpy. It's a **composite
query engine** where bpy handles ground truth ("what exists"), our LiveGraph handles
relationship reasoning ("what connects to what"), and the extracted schema handles
validation ("is this a real socket identifier"). Tools fuse all three transparently.
