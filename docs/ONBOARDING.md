# Agent onboarding prompt

Paste the block below into a fresh VSCode/Cursor agent working in this repo.

---

You are continuing work on **blender-synthgen-mcp**, a Python toolkit that helps an AI agent
generate **3D synthetic data in Blender procedurally** (structural variation from Geometry
Nodes + per-instance shading variation + compositor passes as ground-truth labels), and that
includes a self-contained Blender addon that runs the MCP server directly inside Blender.

## First, read these (in order), then summarize the project back to me in 5 bullets
1. `README.md` and `ROADMAP.md` (what it is, current phase, what's next)
2. `knowledge/procedural_paradigm.md` — the **constitution**: *derive, don't set*
3. `knowledge/scene_graph_contexts.md` — the scene-graph **context/edge spec** (the design of record for the code you'll write)
4. `knowledge/attribute_bridge.md` — GN↔shader attribute bridge (tier-② edges)
5. Skim `knowledge/houdini_to_geonodes.md` and `knowledge/cop_to_compositor.md`

## Non-negotiable principles
- **Grounding, not memory.** Never guess Blender node/socket identifiers. Query the extracted
  schema: `python -m synthgen.schema.query show "Store Named Attribute"` (also `--shader`,
  `--compositor`). Socket *label ≠ identifier* (e.g. "Group ID" → `Group Index`).
- **Derive, don't set.** Prefer authoring/rewiring node graphs over destructive `bpy.ops`
  scene edits. Read-only first; any mutation is graph-diff, never a destructive command.
- **The scene graph is a lazy, pull-based view** over bpy (an edge is computed only when a
  traversal pulls it). The JSON snapshot is a projection for offline/diff use, not the source.
- **Complete up to Blender's data model.** Tier-① = native pointer (walk directly), tier-② =
  reconstructed by name/index via cook-then-read, tier-③ = ontological gap (record, never
  fabricate).

## Repo map
- `src/synthgen/extract/` — node-schema extractors (run inside Blender / hython)
- `src/synthgen/schema/query.py` — grounded-schema query (lib + CLI)
- `src/synthgen/scenegraph/` — `protocol.py` (interface), `traverse.py` (algorithms),
  `backend_snapshot.py` (offline JSON), `backend_bpy.py` (live lazy walker, tier-①)
- `data/schemas/` — grounded Blender 5.2 + Houdini 22 node schemas (committed on purpose)
- `knowledge/` — the agent brain; `skill/SKILL.md` — Claude Code skill
- `addon/synthgen_mcp/` — Blender addon: SSE MCP server + main-thread executor + N-panel UI

## How to work here
- Tests are offline (no Blender): `pip install -e ".[dev]" && pytest` (or `PYTHONPATH=src pytest`).
  Keep them green; add tests with new code.
- ~70% of the code is pure Python and testable without Blender. Only `backend_bpy.py` needs it.
- This machine has **Blender 5.2** at `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`
  and **Houdini 22**. Run bpy code headless with:
  `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b -P script.py` (or on a
  .blend: add `path\to.blend` before `-P`).

## Your immediate task (Phase 2)
`backend_bpy.LiveGraph`'s **tier-① generators are written but never run against real Blender.**
Do this:
1. Write `scripts/validate_livegraph.py` that, run via `blender -b [file.blend] -P`, builds a
   `LiveGraph`, walks from each object with `traverse.reachable`, and prints the nodes/edges it
   finds (counts by edge type). Handle `sys.path` so `synthgen` imports inside Blender.
2. Run it on a real scene (ask me for a .blend, or build a tiny one in the script) and fix any
   place the real bpy API disagrees with the generators (socket access, `node_group`, material
   slots, the **modifier-boundary object-reference gotcha** in `scene_graph_contexts.md`).
3. Then implement **tier-② `attr_bridge`** in `LiveGraph`: cook the depsgraph, read evaluated
   `obj.data.attributes` and `depsgraph.object_instances` (authoritative attribute names), join
   with shader `ShaderNodeAttribute.attribute_name` and GN Store/Capture provenance → emit
   `attr_bridge` edges tagged `tier=2, state_dependent=True`. Add tests using the snapshot
   backend where possible.

## Definition of done for this task
Tier-① `LiveGraph` verified against a real .blend (script committed under `scripts/`), tier-②
`attr_bridge` implemented and demonstrated on a scene that has a GN-written attribute read by a
material, ROADMAP updated, tests green. Commit in logical steps; don't push without asking me.

## Gotchas already discovered (don't relearn these)
- Blender text-editor datablocks are stale snapshots — edit files on disk, use Text→Open/Reload.
- Blender **5.x removed `scene.node_tree`**; the compositor is a node-group datablock
  (`scene.compositing_node_group`). Compositor `Gamma` node is dead; `Zcombine` is alive.
- GN attribute *name* on a Store node can be a literal socket default OR come from the modifier
  interface / an upstream node — resolve tier-② by **evaluated `.attributes`**, not by parsing.
