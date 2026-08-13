# Roadmap

From grounded design spike → iterable product. Each phase is independently useful.

| Phase | Deliverable | State |
|---|---|---|
| **0. Scaffold** | repo structure, README, this roadmap, existing artifacts homed, `git init` | ✅ done |
| **1. Package the spike** | extractors + `schema.query` as clean lib+CLI, `pyproject`, first tests | 🟡 ~80% (extractors + query in; more tests wanted) |
| **2. Scene-graph walker** | protocol + traversal + snapshot backend + fixture tests ✅; tier-① live bpy generators ✅ validated headless against Blender 5.2 ✅; tier-② `attr_bridge` (cook-then-read via `evaluated_geometry().instances_pointcloud()`) ✅; driver edges ✅; Scene Collection root ✅; adversarial build→validate→diff pipeline in `dev_tasks/001_initial_graph_validation/` | ✅ done |
| **3. MCP layer** | thin composable server exposing read-only tools (schema query, graph walk, `impact_set`); wire into Cursor + Claude Code | ⬜ gated on the MCP-wiring + security decision |
| **4. Knowledge → skill/rules** | `skill/SKILL.md` + `.cursor/rules`; the build→verify loop protocol | 🟡 docs exist, packaging pending |
| **5. Mutation** | graph-diff apply (add node / rewire / retarget) — never destructive scene ops | ⬜ |
| **6. Synthetic-data pattern atlas** | SOP→GN operation atlas + domain-randomization recipes (per-instance materials, seg/depth/normal passes, camera/light randomization) | ⬜ scoped |

## Design decisions locked (see `knowledge/`)

- **Grounding, not memory** — extract schemas from the app itself; the agent queries them.
- **Derive, don't set** — procedural-first; destructive `bpy.ops` is a last resort.
- **Walker is a lazy, pull-based view** over bpy (Houdini-style cook-on-pull); the JSON
  snapshot is a `materialize(walk(all))` projection for offline/diff only.
- **Complete up to Blender's data model** — authorability ⇒ introspectability; the only true
  gaps (USD stage, PDG) are outside Blender's ontology, recorded as such, never fabricated.
- **Tier-② edges resolved by cook-then-read** (evaluated `.attributes`) joined with the static
  graph for provenance; each such edge tagged `state_dependent`.

## Dev loop

~70% is pure Python (traversal algorithms, schema query, snapshot backend) — testable in
Cursor/VSCode with fixtures, **no Blender running**. Only the live bpy backend needs Blender,
and that is testable headlessly via `pip install bpy` (match the version) in CI.

## Open decisions

- **Which Blender MCP** to compose with (ahujasid vs official) + **security posture** for
  arbitrary code execution — gates Phase 3.
- **Blender-side install shape**: `pip install` into Blender's python vs an addon shim.
