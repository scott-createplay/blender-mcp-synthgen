# Scatter on Surface — Plan of Record (v0.2)

## Summary

Rebuild the scatter asset from scratch as an attribute-centric GN node group
that follows the well-known attribute contract (`knowledge/well_known_attributes.md`).
The scatter reads density from a named attribute, writes `pscale`, `orient`, `id`,
`N` on output points. Outputs a **point cloud** — instancing is a separate
downstream asset. Supports both density mode and exact count mode, with
interface-ready relaxation parameters (not yet wired in v0.2).

## Reference

- Houdini Scatter SOP: https://www.sidefx.com/docs/houdini/nodes/sop/scatter.html
- Well-known attributes: `knowledge/well_known_attributes.md`
- Current v0.1 asset: `assets/scatter.blend` (to be replaced)

## Architecture

### Attribute-centric design

The scatter outputs a **point cloud with well-known attributes**. Instancing
is a separate downstream concern (a dedicated Instance asset or user-wired
Instance on Points node). The scatter's job ends at producing points with
the right attributes.

If the user (or an upstream asset) has already written `pscale` or `orient`
on the input geometry, those values flow through. The scatter's own computed
values are defaults that can be overridden by upstream attributes.

### Read attributes (input)

| Attribute | String parameter | Default name | Fallback if missing |
|-----------|-----------------|--------------|---------------------|
| density weight | Density Attribute | `"density"` | 1.0 (uniform) |

When the Density Attribute string is empty, no attribute lookup occurs —
Density Max applies uniformly. When set, the Named Attribute node reads
the float attribute and multiplies Density Max per element.

### pscale passthrough rule

**The scatter does NOT overwrite upstream pscale by default.** If the user
defined `pscale` upstream, it flows through untouched. The scatter reads it
for relaxation radii (influence bubble per point) but never modifies it.

When no upstream `pscale` exists, the scatter initializes it to 1.0 — giving
the relax uniform radii and the instancer uniform scale.

Scale randomization is **opt-in** via `Randomize Scale` (bool, default false).
Only when true does the scatter write random values (Scale Min → Scale Max)
into `pscale`. When false, Scale Min / Scale Max are irrelevant.

This follows the Houdini principle: scatter distributes points, it doesn't
redefine their scale. Scale authorship is a separate upstream concern.

### Write attributes (output)

The scatter stores these on the scattered points BEFORE instancing:

| Attribute | Type | Domain | Source |
|-----------|------|--------|--------|
| `pscale` | FLOAT | POINT | **Passthrough from upstream** (or 1.0 if missing). Only overwritten when Randomize Scale = true → random(Scale Min, Scale Max). |
| `orient` | QUATERNION | POINT | Rotation from Distribute Points (aligns to surface normal) |
| `N` | FLOAT_VECTOR | POINT | Surface normal at scatter point |
| `id` | INT | POINT | Unique sequential ID per scattered point |

Downstream Instance on Points reads `pscale` (via Named Attribute → Combine XYZ
for uniform scale) and `orient` (via Named Attribute) from the output points.

### Why this matters

- An upstream modifier can store `pscale` on the mesh before scattering.
  The scatter passes it through — upstream scale control just works. The
  relax phase uses it for influence radii, and the instancer reads it for
  instance size. No re-wiring, no surprises.
- A downstream shader can read `Cd`, `pscale`, or `id` via the attribute
  bridge without knowing they came from the scatter.
- The agent can query `graph_attribute_trace` to see the full provenance
  chain from density producer → scatter → shader.

## Interface (v0.2)

```
Geometry           (NodeSocketGeometry)    — surface to scatter on

— Distribution —
Density Attribute  (NodeSocketString)      — name of float attribute modulating
                                             density (empty = uniform)
                                             [default "density"]
Density Max        (NodeSocketFloat)       — ceiling on point density, points per
                                             unit area [0.1–10000, default 10]
Count              (NodeSocketInt)         — target point count (when Use Count = true)
                                             [1–1000000, default 100]
Use Count          (NodeSocketBool)        — true = count mode, false = density mode
                                             [default false]

— Relaxation —
Relax Iterations   (NodeSocketInt)         — push/reproject passes; 0 = pure random
                                             [0–20, default 0]
Scale Radii By     (NodeSocketFloat)       — relaxation influence multiplier;
                                             0 = disable, <1 = clumpy, >1 = aggressive
                                             [0–2, default 1.0]

— Scale —
Scale Attribute    (NodeSocketString)      — attribute name for per-point uniform scale
                                             [default "pscale"]
Randomize Scale    (NodeSocketBool)        — true = overwrite scale attr with random
                                             values; false = pass through upstream
                                             [default false]
Scale Min          (NodeSocketFloat)       — min random scale (only when Randomize Scale
                                             = true) [0.01–10, default 0.8]
Scale Max          (NodeSocketFloat)       — max random scale (only when Randomize Scale
                                             = true) [0.01–10, default 1.2]

— General —
Seed               (NodeSocketInt)         — distribution randomness [default 0]
```

Output: Point cloud geometry with well-known attributes on the points.

## Internal graph structure

```
┌─────────────────────────────────────────────────────────────────────┐
│ PHASE 1: DISTRIBUTE                                                │
│                                                                    │
│  Group Input.Geometry                                              │
│       │                                                            │
│       ├──→ [if Use Count]:                                         │
│       │      Face Area → Attribute Statistic (Sum) → total_area    │
│       │      Math: count / total_area × 1.1 → computed_density     │
│       │                                                            │
│       ├──→ [density attribute lookup]:                              │
│       │      Named Attribute (Density Attribute string)            │
│       │        ├─ Exists? → Switch: attr value / 1.0               │
│       │        └─ Value (float, 0–1)                               │
│       │                                                            │
│       ├──→ Switch (Use Count): computed_density OR Density Max      │
│       │      × density_attr_value → effective density              │
│       │                                                            │
│       └──→ Distribute Points on Faces (RANDOM mode)                │
│              ├─ Mesh: input geometry                               │
│              ├─ Density: effective density                         │
│              ├─ Seed: Seed parameter                               │
│              ├─ outputs: Points, Rotation, Normal                  │
│              └──→ [if Use Count]: Delete Geometry (Index >= Count)  │
│                                                                    │
├─────────────────────────────────────────────────────────────────────┤
│ PHASE 2: RELAX (when Relax Iterations > 0)                         │
│                                                                    │
│  Repeat Zone (iterations = Relax Iterations):                      │
│    1. Push apart — Sample Nearest, compute repulsion vector,       │
│       scale by (Scale Radii By × radius), nudge position           │
│    2. Snap back — Sample Nearest Surface on input mesh,            │
│       project points back to surface                               │
│                                                                    │
│  When Relax Iterations = 0, Repeat Zone is skipped (passthrough).  │
│                                                                    │
├─────────────────────────────────────────────────────────────────────┤
│ PHASE 3: STORE WELL-KNOWN ATTRIBUTES                               │
│                                                                    │
│  pscale resolution:                                                │
│    Named Attribute (Scale Attribute) → Exists?                     │
│    Switch: exists → upstream value, else → 1.0 = base pscale      │
│    Switch (Randomize Scale): true → Random(Min,Max), false → base  │
│    → Store Named Attribute (Scale Attribute string, FLOAT, POINT)  │
│                                                                    │
│  Store Named Attribute "orient":                                   │
│    Rotation from Distribute Points → store on points               │
│                                                                    │
│  Store Named Attribute "N":                                        │
│    Normal from Distribute Points → store on points                 │
│                                                                    │
│  Store Named Attribute "id":                                       │
│    Index → store on points (unique per point)                      │
│                                                                    │
│  Last Store Named Attribute → Group Output                         │
└─────────────────────────────────────────────────────────────────────┘
```

## Implementation stages

### Prerequisites

Before starting, read:
- `knowledge/well_known_attributes.md` — the attribute contract
- `knowledge/procedural_paradigm.md` — derive, don't set
- `assets/scatter.md` — current manifest (will be rewritten)

The current v0.1 node group in `assets/scatter.blend` should be deleted and
rebuilt from scratch. The new graph is structurally different — patching v0.1
would be harder than rebuilding.

### Stage 1: Scaffold and distribute

**Goal:** New node group with RANDOM distribute, Density Max, and density
attribute lookup. No count mode, no relaxation, no instancing yet.

1. Delete existing "Scatter on Surface" node group if present.
2. Create new GeometryNodeTree "Scatter on Surface".
3. Add interface parameters:
   - INPUT: Geometry (NodeSocketGeometry)
   - INPUT: Density Attribute (NodeSocketString, default "density")
   - INPUT: Density Max (NodeSocketFloat, default 10, min 0.1, max 10000)
   - INPUT: Seed (NodeSocketInt, default 0)
   - OUTPUT: Geometry (NodeSocketGeometry)
4. Add nodes: Group Input, Group Output, Distribute Points on Faces,
   Named Attribute (FLOAT), Switch (FLOAT).
5. Set Distribute Points to RANDOM mode.
6. Wire density attribute lookup:
   - Named Attribute reads Density Attribute string.
   - Switch: if Exists → attr value, else → 1.0.
   - Math: Density Max × attr_or_1 → Distribute.Density.
7. Wire: Group Input.Geometry → Distribute.Mesh, Distribute.Seed from Seed param.
8. Wire: Distribute.Points → Group Output.Geometry (temporary, for testing).
9. Layout and test: create a test plane, apply modifier, verify points appear.
10. Test with density attribute: store a float attr upstream, set string, verify
    spatial masking works.

**Verify:** Points scatter on surface. Density attribute modulates distribution.
Empty string = uniform density.

### Stage 2: Count mode

**Goal:** Add exact count mode with oversample-and-trim.

1. Add interface parameters:
   - INPUT: Count (NodeSocketInt, default 100, min 1, max 1000000)
   - INPUT: Use Count (NodeSocketBool, default false)
2. Add nodes: Face Area, Attribute Statistic, Math (divide, multiply),
   Switch (FLOAT), Delete Geometry, Compare (Index >= Count).
3. Wire count path:
   - Face Area → Attribute Statistic.Attribute (on input mesh geometry).
   - Attribute Statistic.Sum = total surface area.
   - Math: Count / total_area × 1.1 = oversample_density.
4. Wire mode switch:
   - Switch (Use Count): true → oversample_density, false → Density Max × attr.
   - Result → Distribute.Density.
5. Wire trim:
   - After distribute: Index node, Compare (Index >= Count), Delete Geometry.
   - Gate the delete on Use Count (only trim in count mode).
6. Layout and test.

**Verify:** Use Count = true, Count = 50 → exactly 50 points on any surface area.
Use Count = false → density-based scatter unchanged from Stage 1.

### Stage 3: Store well-known attributes

**Goal:** Write orient, N, id on the scattered points. Initialize pscale to
1.0 if missing upstream. Optionally randomize pscale (gated by bool).

1. Add interface parameters:
   - INPUT: Scale Attribute (NodeSocketString, default "pscale")
   - INPUT: Randomize Scale (NodeSocketBool, default false)
   - INPUT: Scale Min (NodeSocketFloat, default 0.8, min 0.01, max 10)
   - INPUT: Scale Max (NodeSocketFloat, default 1.2, min 0.01, max 10)
2. Add nodes: Named Attribute (reads Scale Attribute string — checks Exists),
   Switch (FLOAT), Random Value (FLOAT), Store Named Attribute × 4,
   Index node for id.
3. Wire pscale initialization and passthrough:
   - Named Attribute reads Scale Attribute string.
   - Switch: if Exists → upstream value (passthrough), else → 1.0.
   - This is the BASE pscale — used for relax radii and instancing.
4. Wire optional scale randomization:
   - Random Value (Scale Min → Scale Max, seed offset +1).
   - Switch (Randomize Scale): true → random value, false → base pscale.
   - Result → Store Named Attribute (Scale Attribute string, FLOAT, POINT).
5. Wire remaining attribute stores (in series on the geometry stream):
   - Store Named Attribute "orient" (QUATERNION, POINT):
     value = Distribute.Rotation output.
   - Store Named Attribute "N" (FLOAT_VECTOR, POINT):
     value = Distribute.Normal output.
   - Store Named Attribute "id" (INT, POINT):
     value = Index.
6. Layout and test: evaluate object, verify attributes exist on output points.

**Verify:**
- No upstream pscale, Randomize Scale = false → pscale = 1.0 on all points.
- Upstream pscale = 0.5, Randomize Scale = false → pscale = 0.5 (passthrough).
- Randomize Scale = true → pscale varies between Scale Min and Scale Max.
- orient, N, id always present.

### Stage 4: Relaxation ✅

**Goal:** Push-based relaxation with surface re-projection in a Repeat Zone.

**Implementation:** Uses `GeometryNodeIndexOfNearest` (self-excluded nearest
neighbor — the key discovery) + `Sample Index` + vector math + `Set Position`
+ `Sample Nearest Surface` snap-back, all inside a Repeat Zone with 2 geometry
items (points + input mesh for snap-back).

Nodes added (13 total):
- Relax Repeat In / Out (2 geometry items: points + mesh)
- Nearest Index (`GeometryNodeIndexOfNearest`)
- Point Position (`GeometryNodeInputPosition`)
- Read Neighbor Pos (`GeometryNodeSampleIndex`, FLOAT_VECTOR)
- Push Direction (`ShaderNodeVectorMath`, SUBTRACT)
- Normalize Push (`ShaderNodeVectorMath`, NORMALIZE)
- Push Amount (`ShaderNodeMath`, MULTIPLY, Scale Radii By × 0.02)
- Scale Push (`ShaderNodeVectorMath`, SCALE)
- Nudge (`GeometryNodeSetPosition`, Offset mode)
- Snap to Surface (`GeometryNodeSampleNearestSurface`, FLOAT_VECTOR)
- Surface Position (`GeometryNodeInputPosition`)
- Apply Snap (`GeometryNodeSetPosition`, Position mode)

**Validated results (50 points, count mode, flat plane):**

| Iterations | min NN | max NN | avg NN | uniformity | CV |
|-----------|--------|--------|--------|-----------|-----|
| 0 | 0.018 | 0.360 | 0.155 | 0.049 | 0.513 |
| 5 | 0.130 | 0.399 | 0.226 | 0.327 | 0.291 |
| 10 | 0.181 | 0.467 | 0.258 | 0.386 | 0.208 |
| 20 | 0.216 | 0.450 | 0.280 | 0.480 | 0.150 |

- 10x uniformity improvement at 20 iterations
- Z stays exactly 0.000 — snap-back holds
- Convergent and stable, no blowup

**Key discovery:** `GeometryNodeIndexOfNearest` naturally excludes self when
finding nearest neighbors. `Sample Nearest` and `Geometry Proximity` do NOT.
This unblocks pure-GN relaxation without even/odd hacks or Python.

### Stage 5: Final interface, save, and manifest

1. Reorder interface parameters to match the v0.2 spec above.
2. Auto-layout the complete graph.
3. Save to `assets/scatter.blend` (overwrite v0.1).
4. Rewrite `assets/scatter.md` manifest:
   - Update parameter table with final identifiers.
   - Document read/write attributes.
   - Document composition patterns with density producers.
   - Document the override pattern (string parameters for attribute names).
   - Update limitations and sweep guidance.
5. Checkpoint.

**Verify:** Fresh Blender → load node group from scatter.blend → apply to mesh
→ set collection → verify instances appear → sweep seeds → verify coherent
output across parameter space.

## GN nodes required

Reference for the implementing agent — all node type IDs grounded against
the Blender 5.2 schema:

| Purpose | Node type ID |
|---------|-------------|
| Distribute points | `GeometryNodeDistributePointsOnFaces` |
| Delete geometry | `GeometryNodeDeleteGeometry` |
| Store named attribute | `GeometryNodeStoreNamedAttribute` |
| Read named attribute | `GeometryNodeInputNamedAttribute` |
| Face area | `GeometryNodeInputMeshFaceArea` |
| Attribute statistic | `GeometryNodeAttributeStatistic` |
| Sample nearest | `GeometryNodeSampleNearest` |
| Sample nearest surface | `GeometryNodeSampleNearestSurface` |
| Blur attribute | `GeometryNodeBlurAttribute` |
| Repeat zone input | `GeometryNodeRepeatInput` |
| Repeat zone output | `GeometryNodeRepeatOutput` |
| Random value | `FunctionNodeRandomValue` |
| Combine XYZ | `ShaderNodeCombineXYZ` |
| Math | `ShaderNodeMath` |
| Compare | `FunctionNodeCompare` |
| Switch | `GeometryNodeSwitch` |
| Index | `GeometryNodeInputIndex` |
| Group input | `NodeGroupInput` |
| Group output | `NodeGroupOutput` |

Socket identifiers: always use `schema_show` to confirm before wiring.
Socket label ≠ identifier.

## Resolved

- [x] Mode switch: `Use Count` bool vs enum property — **bool**, simpler for
      agents and works with set_parameter.
- [x] Instancing: removed from scatter scope — **separate asset**.
- [x] GN self-proximity: `Geometry Proximity` and `Sample Nearest` return
      distance=0 on self-cloud. **Solved** with `Index of Nearest` which
      naturally excludes self. Relaxation fully wired in pure GN.

## Open questions

- [ ] Blur Attribute vs explicit repulsion for relaxation — prototype needed.
      Even/odd index split is a candidate for approximate nearest neighbor in GN.
- [ ] `source_prim` and `source_uv`: does Distribute Points on Faces expose
      these in Blender 5.2, or do we need to compute them separately?
- [ ] Max Relax Radius: include in v0.3 or defer? Prevents blowup in
      low-density areas but adds another parameter.
