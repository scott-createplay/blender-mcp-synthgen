# Roadmap

From grounded design spike → iterable product. Each phase is independently useful.

| Phase | Deliverable | State |
|---|---|---|
| **0. Scaffold** | repo structure, README, this roadmap, existing artifacts homed, `git init` | ✅ done |
| **1. Package the spike** | extractors + `schema.query` as clean lib+CLI, `pyproject`, first tests | ✅ done |
| **2. Scene-graph walker** | protocol + traversal + snapshot backend + fixture tests; tier-① live bpy generators validated headless against Blender 5.2; tier-② `attr_bridge` (cook-then-read); driver edges; adversarial build→validate→diff pipeline | ✅ done |
| **3. MCP layer** | composable MCP server: schema query (4 tools), graph introspection (6 tools), setup (4 tools), procedural authoring (9 tools), verify (1 tool), escape hatch (1 tool) — 25 tools total, grounding-enforced, dirty-flag auto-invalidation | 🟡 Stages 1–4 done; Stage 5 (Layer 1 gaps, Layer 4 sweep/render) + Stage 6 (housekeeping) remain |
| **4. Knowledge → skill/rules** | `skill/SKILL.md` + `.cursor/rules`; the build→verify loop protocol | 🟡 docs exist, packaging pending |
| **5. Mutation** | graph-diff apply (add node / rewire / retarget) — never destructive scene ops | ✅ subsumed by Phase 3 Layer 2 tools |
| **6. Synthetic-data pattern atlas** | SOP→GN operation atlas + domain-randomization recipes (per-instance materials, seg/depth/normal passes, camera/light randomization) | ⬜ scoped |

## Phase 3 — MCP layer (current)

**Transport:** composes with ahujasid/blender-mcp via `SocketTransport` (TCP, port 9876).
Auto-detects `DirectBpyTransport` when bpy is importable. Version-aware schema resolution
from `bpy.app.version` with closest-match fallback.

**Grounding:** enforced, not advisory. Invalid node types, sockets, and settings never
reach Blender. Fuzzy "did you mean?" suggestions via `difflib.get_close_matches`.

**Tools by layer:**
- **Layer 1 (setup):** `create_object`, `create_material`, `assign_material`, `set_parent`
- **Layer 2 (procedural):** `add_gn_modifier`, `add_node`, `link_sockets`, `set_node_property`,
  `set_socket_default`, `expose_parameter`, `add_driver`, `wire_attr_bridge`, `wire_compositor_pass`
- **Layer 3 (introspection):** `graph_nodes`, `graph_neighbors`, `graph_reachable`,
  `graph_impact_set`, `graph_attribute_trace`, `graph_snapshot`
- **Schema:** `schema_find`, `schema_show`, `schema_socket`, `schema_setting`
- **Verify:** `verify_attribute_exists`
- **Escape hatch:** `execute_python` (tagged ungrounded, triggers dirty flag)

**Remaining (Stages 5–6):** Layer 1 gaps (`edit_mesh`, `import_asset`, `configure_render`,
`add_keyframes`), Layer 4 (`set_parameter`, `render`, `sweep`, `export_labels`), provenance
snapshots, agent guidance in tool descriptions, file layout documentation.

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
- **Transport:** ahujasid/blender-mcp (TCP socket, port 9876). Security: advisory/tagged,
  not enforced.
- **File layout:** `blender.py` consolidates setup + procedural tools (deliberate
  simplification vs original POR's split).

## Dev loop

~70% is pure Python (traversal algorithms, schema query, snapshot backend) — testable in
Cursor/VSCode with fixtures, **no Blender running**. Only the live bpy backend needs Blender,
and that is testable headlessly via `pip install bpy` (match the version) in CI.

113 offline tests pass (`pip install -e ".[dev]" && pytest`).
