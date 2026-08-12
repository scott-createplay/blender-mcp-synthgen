# Roadmap

From grounded design spike → iterable product. Each phase is independently useful.

| Phase | Deliverable | State |
|---|---|---|
| **0. Scaffold** | repo structure, README, this roadmap, existing artifacts homed, `git init` | ✅ done |
| **1. Package the spike** | extractors + `schema.query` as clean lib+CLI, `pyproject`, first tests | 🟡 ~80% (extractors + query in; more tests wanted) |
| **2. Scene-graph walker** | `neighbors()`/`resolve()` protocol + tier-① generators (pointer walks), snapshot backend + fixture tests, then live bpy backend + tier-② (cook-then-read) | ⬜ designed ([`knowledge/scene_graph_contexts.md`](knowledge/scene_graph_contexts.md)) |
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
