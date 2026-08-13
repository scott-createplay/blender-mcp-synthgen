# Diff Report — Walker vs Ground Truth

## Inputs

- **Ground truth:** `scenes/ground_truth.json` (23 nodes, 24 edges, 1 attribute)
- **Walker report:** `validation/walker_report.json` (10 nodes, 21 edges, 0 errors)

## Expected discrepancies (by design)

**13 NODE: ids** (e.g. `NG:GN_TestTree/NODE:Store Named Attribute`,
`MAT:TestMaterial/NODE:Attribute`, etc.) are in the ground truth but not in the walker's
`nodes()` output. This is correct — the protocol defines `nodes()` as "bounded top-level
enumeration; deeper ids are reached via neighbors()." All 13 NODE: ids appear as edge
destinations (`tree_contains_node`) and in the `reachable_from` sets. Not a bug.

## Finding 1: Missing `COL:Scene Collection`

| | Ground truth | Walker |
|---|---|---|
| Node `COL:Scene Collection` | present | **missing** |
| Edge `COL:Scene Collection → COL:TestRoot` | present | **missing** |

**Root cause:** `LiveGraph.nodes()` iterates `bpy.data.collections`, but the root Scene
Collection (`scene.collection`) is not in `bpy.data.collections` — it's a special built-in
collection that Blender treats differently.

**Impact:** The scene's collection hierarchy is incomplete at the root. Any traversal
starting from the Scene Collection won't work, and `impact_set` can't trace back to it.

**Fix:** Yield `_col(self.scene.collection)` in `nodes()` and ensure `_collection()` can
resolve it.

## Finding 2: No `drives` edges

| | Ground truth | Walker |
|---|---|---|
| Edge `OBJ:DriverSource → OBJ:ChildCube` (`drives`) | present | **missing** |
| Edge type `drives` | 1 edge | **0 edges** |

**Root cause:** `LiveGraph._object()` traverses `parent`, `instance_collection`,
`modifiers`, and `material_slots` — but never inspects `obj.animation_data.drivers`.
Driver edges are completely unimplemented.

**Impact:** The walker is blind to parametric relationships driven by drivers. This
affects `impact_set` (can't answer "what breaks if I change this object?") and any
traversal that depends on driver connectivity.

**Fix:** In `_object()`, check `obj.animation_data` and iterate `.drivers`. For each
FCurve's driver, inspect `.variables[].targets[].id` to find referenced objects and
emit `drives` edges.

## Finding 3: `references_object` not in flat edge list (not a walker bug)

| | Ground truth | Walker flat edges | Walker reachable |
|---|---|---|---|
| `NG:GN_TestTree/NODE:Object Info → OBJ:InstanceTarget` | present | **missing** | **present** (InstanceTarget in reachable set from ChildCube) |

**Root cause:** The validator script only called `neighbors()` on the 10 nodes returned
by `nodes()`. Since NODE: ids are discovered via edges (not enumerated by `nodes()`),
their outgoing edges (like `references_object`) only appear during BFS traversal.

**Impact:** None — the walker correctly generates this edge during traversal. The BFS
`reachable()` from `OBJ:ChildCube` includes `OBJ:InstanceTarget`, confirming the
`references_object` edge from `NODE:Object Info` fires correctly.

**Fix:** No walker fix needed. The validator methodology could be improved by recursively
calling `neighbors()` on newly discovered NODE: ids, but this is a tooling enhancement,
not a correctness issue.

## Summary

| # | Finding | Type | Status |
|---|---|---|---|
| 1 | Scene Collection missing from `nodes()` | Walker bug | **needs fix** |
| 2 | No driver edge generation | Walker gap | **needs fix** |
| 3 | `references_object` absent from flat list | Validator methodology | correct behavior |
