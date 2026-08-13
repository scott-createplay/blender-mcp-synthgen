# POR — Initial Scene-Graph Validation

## Goal

Validate that the tier-1 `LiveGraph` generators in `backend_bpy.py` produce correct
nodes and edges when run against a real Blender scene, then implement and validate
tier-2 `attr_bridge` edges. This closes Phase 2 of the ROADMAP.

## The problem with naive validation

If a single agent both **builds** the test scene and **validates** the walker output,
the test is a closed loop — the agent already knows the structure, so its expectations
mirror its construction. Bugs where both the scene-build and the walker share the same
wrong assumption will pass silently.

## Approach: adversarial delegation

Break the loop by splitting the work across independent agents that cannot see each
other's output:

### Agent 1 — Scene Builder

**Input:** feature-coverage checklist (below), synthgen schema query tool, Blender 5.2 API.
**Output:** `scenes/test_scene.blend` + `scenes/ground_truth.json` manifest.
**Cannot see:** the walker code in `scenegraph/`.

Builds a `.blend` programmatically via `scripts/build_test_scene.py` (run headless),
targeting the full feature coverage matrix. Also writes a ground-truth manifest — a
JSON recording every expected node, edge, attribute name, and relationship — so the
scene's intent is machine-diffable without reading the build script.

### Agent 2 — Walker Validator

**Input:** the `.blend` file path, the `synthgen` package (scenegraph + schema), Blender 5.2.
**Output:** walker report (`validation/walker_report.json`).
**Cannot see:** the build script or the ground-truth manifest.

Writes `scripts/validate_livegraph.py`. Loads the `.blend` in headless Blender, builds
a `LiveGraph`, runs `traverse.reachable` from each object, and reports every node and
edge it finds (counts by type, full edge list, attribute names discovered).

### Pass 3 — Diff / Reconciliation

**Input:** `ground_truth.json` + `walker_report.json`.
**Output:** mismatch report — missing edges, extra edges, wrong types, missing attributes.

Compare walker output against the builder's manifest. Any disagreement is a real signal:
either the walker has a bug, the build script has a bug, or both share a wrong assumption
about Blender's data model (which is the most valuable kind of finding).

After reconciliation, fix bugs in the walker (or the build script), re-run, iterate until
the diff is clean.

## Feature-coverage matrix

The test scene must exercise every tier-1 edge type and set up the tier-2 attr_bridge:

| Feature | Why | Exercises |
|---|---|---|
| Object hierarchy (parent/child) | tier-1 parent edge | `obj.parent` pointer |
| Collection hierarchy (nested) | tier-1 collection membership | `collection.objects`, `collection.children` |
| GN modifier on an object | tier-1 modifier → node_group | `obj.modifiers`, `mod.node_group` |
| Node group with internal links | tier-1 node/link traversal | `node_tree.nodes`, `node_tree.links` |
| Group input exposing a parameter | tier-1 interface sockets | modifier interface traversal |
| Material slot → material | tier-1 material assignment | `obj.material_slots` |
| Shader node tree with links | tier-1 shader node traversal | `mat.node_tree` |
| `ShaderNodeAttribute` reading a named attr | tier-2 sink | `node.attribute_name` |
| GN `Store Named Attribute` writing a named attr | tier-2 source | attribute provenance |
| Instance on Points (instancer) | tier-1 + depsgraph instances | `depsgraph.object_instances` |
| Compositor node group (5.x path) | tier-1 compositor traversal | `scene.compositing_node_group` |
| Driver on a value | tier-1 driver edge | `obj.animation_data.drivers` |
| Object reference in GN modifier (e.g. Object Info) | modifier-boundary gotcha | cross-object reference from inside a node group |

## Tier-2 `attr_bridge` (implemented after tier-1 is validated)

Once the walker's tier-1 edges are confirmed correct:

1. Cook the depsgraph (`depsgraph.update()`)
2. Read evaluated `obj.data.attributes` — these are the authoritative attribute names
3. Read `depsgraph.object_instances` for instanced geometry attributes
4. Join with shader `ShaderNodeAttribute.attribute_name` (sinks) and GN Store/Capture
   node provenance (sources)
5. Emit `attr_bridge` edges tagged `tier=2, state_dependent=True`
6. Test via snapshot backend where possible (offline), validate via headless bpy

## Definition of done

- [ ] `scripts/build_test_scene.py` — builds the test `.blend` + ground-truth manifest
- [ ] `scripts/validate_livegraph.py` — runs walker blind, produces report
- [ ] Diff is clean (or all mismatches explained and fixed)
- [ ] Tier-2 `attr_bridge` implemented in `LiveGraph`
- [ ] `attr_bridge` demonstrated on the test scene (GN-written attr read by material)
- [ ] Offline tests added (snapshot backend) — `pytest` green
- [ ] ROADMAP updated
- [ ] Commits logical, not pushed without asking

## File layout (expected)

```
dev_tasks/001_initial_graph_validation/
  POR.md                  ← this file
scripts/
  build_test_scene.py     ← Agent 1 output (run via blender -b -P)
  validate_livegraph.py   ← Agent 2 output (run via blender -b scene.blend -P)
scenes/                   ← gitignored (binary .blend) or committed if small
  test_scene.blend
  ground_truth.json
validation/
  walker_report.json
  diff_report.md
```

## Decisions

- **Rebuild on demand.** The `.blend` is not committed — `build_test_scene.py` is the
  source of truth. Add `scenes/*.blend` to `.gitignore`.
- **Wild `.blend` smoke test** — follow-up task (002), not part of this POR.
