# Roadmap

From grounded design spike → iterable product. Each phase is independently useful.

| Phase | Deliverable | State |
|---|---|---|
| **0. Scaffold** | repo structure, README, this roadmap, existing artifacts homed, `git init` | ✅ done |
| **1. Package the spike** | extractors + `schema.query` as clean lib+CLI, `pyproject`, first tests | ✅ done |
| **2. Scene-graph walker** | protocol + traversal + snapshot backend + fixture tests; tier-① live bpy generators validated headless against Blender 5.2; tier-② `attr_bridge` (cook-then-read); driver edges; adversarial build→validate→diff pipeline | ✅ done |
| **3. MCP layer** | composable MCP server: schema query (4), graph introspection (6), setup (8), procedural authoring (9), pipeline (4), verify (1), escape hatch (1) — 33 tools total, grounding-enforced, dirty-flag auto-invalidation, provenance snapshots | ✅ done |
| **3b. Blender addon** | Self-contained Blender addon bundling the MCP server as an SSE endpoint. Install zip → enable → connect from any IDE. Main-thread executor, N-panel UI, build script. | ✅ done |
| **4. Knowledge → skill/rules** | `skill/SKILL.md` + `.cursor/rules`; the build→verify loop protocol | 🟡 docs exist, packaging pending |
| **5. Mutation** | graph-diff apply (add node / rewire / retarget) — never destructive scene ops | ✅ subsumed by Phase 3 Layer 2 tools |
| **6. Synthetic-data pattern atlas** | SOP→GN operation atlas + domain-randomization recipes (per-instance materials, seg/depth/normal passes, camera/light randomization) | ⬜ scoped |

## Phase 3 — MCP layer

**Transport:** self-contained Blender addon (`addon/synthgen_mcp/`) runs an SSE MCP server
on port 8400 with direct `bpy` access via a main-thread executor. No external addon
dependency. Version-aware schema resolution from `bpy.app.version` with closest-match
fallback.

**Grounding:** enforced, not advisory. Invalid node types, sockets, and settings never
reach Blender. Fuzzy "did you mean?" suggestions via `difflib.get_close_matches`.

**Tools by layer (33 total):**
- **Layer 1 (setup, `blender.py`):** `create_object`, `create_material`, `assign_material`,
  `set_parent`, `configure_render`, `import_asset`, `edit_mesh`, `add_keyframes`
- **Layer 2 (procedural, `blender.py`):** `add_gn_modifier`, `add_node`, `link_sockets`,
  `set_node_property`, `set_socket_default`, `expose_parameter`, `add_driver`,
  `wire_attr_bridge`, `wire_compositor_pass`
- **Layer 3 (introspection, `graph.py`):** `graph_nodes`, `graph_neighbors`, `graph_reachable`,
  `graph_impact_set`, `graph_attribute_trace`, `graph_snapshot`
- **Layer 4 (pipeline, `pipeline.py`):** `set_parameter`, `render`, `sweep`, `export_labels`
- **Schema (`schema.py`):** `schema_find`, `schema_show`, `schema_socket`, `schema_setting`
- **Verify (`verify.py`):** `verify_attribute_exists`
- **Escape hatch (`blender.py`):** `execute_python` (tagged ungrounded, triggers dirty flag)

**File layout:** `blender.py` consolidates Layer 1 (setup) + Layer 2 (procedural authoring).
`pipeline.py` holds Layer 4 (orchestration: parameters, render, sweep, labels) — structurally
different from mutation tools (it composes operations, handles loops, interacts with the
filesystem for provenance). `graph.py`, `schema.py`, `verify.py` unchanged.

See `dev_tasks/003_mcp_stabilize_and_ground/HANDOFF.md` for full details.

## Design decisions locked (see `knowledge/`)

- **Grounding, not memory** — extract schemas from the app itself; the agent queries them.
- **Derive, don't set** — procedural-first; destructive `bpy.ops` is a last resort.
- **Walker is a lazy, pull-based view** over bpy (Houdini-style cook-on-pull); the JSON
  snapshot is a `materialize(walk(all))` projection for offline/diff only.
- **Complete up to Blender's data model** — authorability ⇒ introspectability; the only true
  gaps (USD stage, PDG) are outside Blender's ontology, recorded as such, never fabricated.
- **Tier-② edges resolved by cook-then-read** (evaluated `.attributes`) joined with the static
  graph for provenance; each such edge tagged `state_dependent`.
- **Transport:** self-contained Blender addon, SSE on port 8400. Security: advisory/tagged,
  not enforced.
- **File layout:** `blender.py` consolidates setup + procedural tools (deliberate
  simplification vs original POR's split).

## Dev loop

~70% is pure Python (traversal algorithms, schema query, snapshot backend) — testable in
Cursor/VSCode with fixtures, **no Blender running**. Only the live bpy backend needs Blender,
and that is testable headlessly via `pip install bpy` (match the version) in CI.

194 offline tests pass (`pip install -e ".[dev]" && pytest`).
