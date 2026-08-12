# Houdini → Blender Geometry Nodes — concept map

**Blender side grounded against 5.2.0 LTS.** Any GN id/socket here is verifiable with
`python query_schema.py show "<node>"`. Houdini side = classic SOP/VEX (recognizable to a
Houdini user); it is the *source* language you're translating **from**, so it need not be
byte-exact — the Blender side must be.

The goal: let a Houdini brain produce **correct** Blender graphs. Read the mental-model
shifts first — most translation errors come from the model differences, not from missing a
node name.

---

## 1. Five mental-model shifts (read these first)

### 1.1 One geometry stream, many component types
Houdini threads one geometry through a SOP chain. Blender GN also threads **one "geometry"**,
but that geometry is a **bundle of component types at once**: mesh, curves, point cloud,
instances, volume, grease pencil. Nodes act on the component(s) they target and pass the rest
through. `Merge` → **`Join Geometry`** (`GeometryNodeJoinGeometry`). "Separate parts" →
`Separate Geometry` / `Separate Components`.

### 1.2 Attributes live on **domains**, not classes
| Houdini attribute class | Blender domain |
|---|---|
| point | `POINT` |
| vertex | `CORNER` (face-corner) |
| primitive | `FACE` (mesh) / `CURVE` (splines) |
| detail (global) | no true detail domain → use a **single field value** / `INSTANCE` or store on all, or capture a statistic |
| — (instances) | `INSTANCE` |
| — (grease pencil layer) | `LAYER` |

There is **no implicit `@P`**: position is a node. Read with **`Position`**
(`GeometryNodeInputPosition`), write with **`Set Position`** (`GeometryNodeSetPosition`:
`Geometry, Selection, Position, Offset`). Same for `Normal` (`GeometryNodeInputNormal` →
`Normal, True Normal`), `Index` (`GeometryNodeInputIndex`, ≈ `@ptnum`/`@primnum`).

### 1.3 Fields ≈ lazy per-element VEX
A Blender **field** is a computation evaluated *per element of whatever domain consumes it* —
conceptually a VEX expression that hasn't run yet. It only "cooks" when a node **captures**
or **stores** it. So:

> **VEX Attribute Wrangle ≈ a field graph terminated by `Capture Attribute` or `Store Named Attribute`.**

`Capture Attribute` (`GeometryNodeCaptureAttribute`, `domain` ∈ POINT/EDGE/FACE/CORNER/CURVE/
INSTANCE/LAYER) freezes a field onto a domain — the moment your lazy expression becomes real
data, like a wrangle writing `@attr`.

### 1.4 No code node — build expressions from nodes
There is no VEX/Python-per-element node. You assemble expressions from:
`ShaderNodeMath` (`Value, Value_001, Value_002`; `operation` enum), `ShaderNodeVectorMath`,
`FunctionNodeCompare`, `FunctionNodeBooleanMath`, `ShaderNodeMapRange` (`fit()`),
`ShaderNodeSeparateXYZ`/`CombineXYZ`, `FunctionNodeRandomValue` (`rand()`, per-element via
`ID`/`Seed`). Ternary `a ? b : c` → **`Switch`** (`GeometryNodeSwitch`) or `Index Switch`.
`@ptnum` → `Index`. Cross-element `point(0,"P",i)` → **`Sample Index`**
(`GeometryNodeSampleIndex`: `Geometry, Value, Index`).

### 1.5 Groups are ephemeral **selection fields**, not stored sets
Houdini groups are first-class, named, persistent. Blender's everyday equivalent is a
**boolean field** flowing into a node's `Selection` input — computed on the spot from
`Compare`/`Boolean Math`. To persist a group, `Store Named Attribute` a `BOOLEAN` and read it
back with `Named Attribute` (which also gives an **`Exists`** output — handy for verification).

---

## 2. SOP → GN crosswalk (grounded Blender ids)

**Generate / primitives**
| Houdini | Blender GN |
|---|---|
| Grid / Box / Tube / Sphere / Line / Circle | `GeometryNodeMesh*` family (Grid, Cube, Cylinder, Cone, UV/Ico Sphere), `GeometryNodeMeshLine` (`Count, Resolution, Start Location, Offset`), Curve primitives `GeometryNodeCurvePrimitive*` (Line, Circle, …) |
| Scatter | **`Distribute Points on Faces`** (`GeometryNodeDistributePointsOnFaces`; `distribute_method` RANDOM/POISSON) |
| Points from Volume | `Distribute Points in Volume` (`GeometryNodeDistributePointsInVolume`) |

**Copy / instance (the synthetic-data core)**
| Houdini | Blender GN |
|---|---|
| Copy to Points | **`Instance on Points`** (`GeometryNodeInstanceOnPoints`: `Points, Selection, Instance, Pick Instance, Instance Index, Rotation, Scale`) |
| Copy Stamp / per-copy variation | **per-instance attributes → the shader** — see `attribute_bridge.md` (this is Copy Stamp done right) |
| Pack / Unpack | instances vs **`Realize Instances`** (`GeometryNodeRealizeInstances`) |
| Instance variation by `Pick Instance` | feed a collection + `Instance Index` |

**Attributes**
| Houdini | Blender GN |
|---|---|
| Attribute Create / Wrangle (write) | field graph → **`Store Named Attribute`** (`data_type`, `domain`) |
| Attribute VOP | field graph (same node vocabulary) |
| Attribute Promote (class→class) | `Capture Attribute` on target domain / `Attribute Statistic` (`GeometryNodeAttributeStatistic`) for reductions |
| Attribute Transfer | **`Sample Nearest Surface`** (`GeometryNodeSampleNearestSurface`) or `Sample Nearest` + `Sample Index` |
| Measure (area/perimeter) | `GeometryNodeInputMeshFaceArea`, edge/curve length inputs |
| Attribute Promote → detail (reduce) | `Attribute Statistic` (Mean/Sum/Min/Max/…) |

**Groups / selection**
| Houdini | Blender GN |
|---|---|
| Group / Group by Range / Expression | boolean **field** into `Selection` (`Compare`, `Boolean Math`) |
| Group by Normal angle | `Normal` → `Vector Math (Dot)` → `Compare` |
| persist a group | `Store Named Attribute` (BOOLEAN) |

**Deform / topology**
| Houdini | Blender GN |
|---|---|
| Transform | `Transform Geometry` (`GeometryNodeTransform`) |
| Point/Peak (move along N) | `Set Position` with `Offset = Normal × amount` |
| Ray | **`Raycast`** (`GeometryNodeRaycast`: `Target Geometry … Is Hit, Hit Position, Hit Normal, Hit Distance, Attribute`) |
| Fuse | `Merge by Distance` (`GeometryNodeMergeByDistance`) |
| PolyExtrude | `Extrude Mesh` (`GeometryNodeExtrudeMesh` → `Mesh, Top, Side`) |
| Subdivide | `Subdivide Mesh` / `Subdivision Surface` (verify: `query_schema.py find Subdiv`) |
| Boolean | `Mesh Boolean` (`GeometryNodeMeshBoolean`) |
| Triangulate / Divide | `Triangulate` (`GeometryNodeTriangulate`), `Dual Mesh` |

**Curves (key for L-systems)**
| Houdini | Blender GN |
|---|---|
| Resample | `Resample Curve` (`GeometryNodeResampleCurve`; `Mode` Count/Length) |
| Carve | `Trim Curve` (`GeometryNodeTrimCurve`) |
| Fillet / round | `Fillet Curve` (`GeometryNodeFilletCurve`) |
| Sweep | `Curve to Mesh` (`GeometryNodeCurveToMesh`: `Curve, Profile Curve, Scale, Fill Caps`) |
| Add / build curve from points | `Points to Curves` (`GeometryNodePointsToCurves`: `Points, Curve Group ID, Weight`) |
| PolyFrame / tangents | `Curve Tangent` (`GeometryNodeInputTangent`), `Normal`, `Spline Parameter` (`Factor, Length, Index`) |
| Convert curve→points | `Curve to Points` (`GeometryNodeCurveToPoints` → `Points, Tangent, Normal, Rotation`) |
| set width/radius | `Set Curve Radius` (`GeometryNodeSetCurveRadius`) |
| NURBS/Bezier/poly type | `Set Spline Type` (`GeometryNodeCurveSplineType`) |
| endpoint/first-last select | `Endpoint Selection` (`GeometryNodeCurveEndpointSelection`) |

**Sampling / lookups**
| Houdini | Blender GN |
|---|---|
| `point()/prim()` cross-lookup | `Sample Index` (by index) |
| nearest point/prim | `Sample Nearest` (→ index) then `Sample Index` |
| xyzdist / attrib transfer surface | `Sample Nearest Surface` |
| VDB sample | `Sample Grid` (`GeometryNodeSampleGrid`) |

---

## 3. VEX → field-graph translation (worked)

```
// VEX                                  // GN field graph  (→ terminate with Store/Capture)
@P.y += 0.5;                            Set Position[ Offset = (0,0,0.5) ]
f@w = fit(@P.x, 0,10, 0,1);            Position→Separate XYZ.X → Map Range(0,10→0,1) → Store "w"(FLOAT,POINT)
i@id = @ptnum;                         Index → Store "id"(INT,POINT)
@Cd = rand(@ptnum);                    Random Value[FLOAT_COLOR, ID=Index] → Store "Cd"(FLOAT_COLOR)
if(@P.y>1) @grp=1;                     Position→Sep.Y → Compare(> 1) → Store "grp"(BOOLEAN)
v@n = point(0,"P", @ptnum+1);          Sample Index[ Value=Position, Index = Index+1 ]
@pscale *= ch("k");                    (multiply by a Group Input value exposed on the modifier)
```

Two rules that eliminate most bugs:
- **Terminate the field.** A field does nothing until a node consumes it — end with
  `Store Named Attribute` (persist) or `Capture Attribute` (freeze for downstream use).
- **Pick the domain deliberately.** `Store`/`Capture` `domain` = the Houdini class you'd have
  written to (`point→POINT`, `prim→FACE/CURVE`, `vertex→CORNER`).

---

## 4. `foreach` → which zone? (Houdini's biggest translation trap)

Blender has **three zones**; Houdini's `foreach`/solver splits across them:

| Houdini pattern | Blender zone | Node ids |
|---|---|---|
| Foreach **independent** piece/point (no feedback) | **For Each Geometry Element** | `GeometryNodeForeachGeometryElementInput` (`Geometry, Selection → Index, Element`) / `…Output` |
| Foreach with **feedback**, fixed **count** (iterate N times, each pass sees the last) | **Repeat** | `GeometryNodeRepeatInput` (`Iterations → Iteration`) / `…Output` (`Item_0` …) |
| **Solver** / time-based accumulation over frames | **Simulation** | `GeometryNodeSimulationInput` (`→ Delta Time`) / `…Output` (`Skip, Item_0` …) |

Rule: **independent → For-Each; recursive/N-times → Repeat; over-time → Simulation.**

---

## 5. L-system / procedural growth (your project)

- **Recursion / generations** → **Repeat zone**: thread the working curve/point set through
  `Item_0`, and each iteration branches/extends it. Store a **`generation`** INT attribute per
  pass (via `Repeat Input.Iteration` → Store) — later drives thickness *and* shading.
- **Branch instancing** → build one segment/leaf, `Instance on Points` onto branch points,
  vary per instance via the **attribute bridge** (thickness, leaf age, color).
- **Taper** → `Spline Parameter.Factor` → `Map Range` → `Set Curve Radius`.
- **Turn curves into geometry** → `Curve to Mesh` (branch profile) / `Curve to Points` +
  `Instance on Points` (leaves).
- **Growth over time** (animated) → **Simulation zone** carrying the structure, appending each
  frame; bake when happy.
- Every per-branch/per-leaf attribute you store (generation, age, thickness, species-id)
  becomes a **shading and label channel for free** — see `attribute_bridge.md`.

---

## 6. What Houdini has that GN does **not** (be honest, plan around it)

| Houdini | GN reality / workaround |
|---|---|
| VEX / arbitrary per-element code | node-built field graphs only; complex logic gets verbose — consider a Python-authored node group |
| Variable-length per-element **arrays** | no true per-element arrays; use extra attributes + `Accumulate Field` / `Sample Index` |
| First-class persistent **groups** | ephemeral selection fields; persist via boolean attributes |
| Full **DOP** solvers / SPH / FEM | only the Simulation zone (much simpler); heavy sims stay in Houdini |
| Deep **VDB** toolset | a subset (Distribute in Volume, Sample Grid, mesh↔volume); not parity |
| CVEX / compiled blocks / stamping expressions | approximate with zones + attributes |
| String-heavy workflows | limited string nodes (`FunctionNode*String`) |

For a synthetic-data pipeline this split is usually fine: **structure + variation + labels**
all live comfortably in GN; only heavy simulation or exotic VDB work needs to stay in Houdini
(and can be baked to geometry/attributes the GN side then consumes).
