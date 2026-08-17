---
asset: SynthGen.Instance on Points
file: scatter.blend
node_group: SynthGen.Instance on Points
category: instancing
catalog_path: SynthGen/Instancing
version: 0.1
blender: "5.2"
---

# Instance on Points

Places instances from a collection onto input points, reading transform
attributes from the geometry. Designed to chain after Scatter on Surface
(or any asset that outputs points with well-known attributes).

## When to use

- Instance objects onto scattered points (vegetation, rocks, debris)
- Any time you have a point cloud with `pscale` / `orient` and want geometry

Do NOT use when:
- You need manual placement of individual objects
- You need non-uniform scaling per axis (extend this asset or use `scale` attr)

## Design intent

The instancer reads **well-known attributes by name**, not through socket
wiring. Wire geometry in, set a collection, and it works — `pscale` drives
uniform scale, `orient` drives rotation. No re-wiring needed between assets.

**Pick Instance** randomly selects which object from the collection each point
gets, seeded by `Seed + Index` for deterministic per-point variation.

## Read attributes

| Attribute | String parameter | Default name | Fallback |
|-----------|-----------------|--------------|----------|
| scale | Scale Attribute | `"pscale"` | 1.0 (uniform) |
| rotation | Rotation Attribute | `"orient"` | identity |

## Write attributes

None. Instances inherit attributes from the source points.

## Parameters

| Name | Identifier | Type | Default | Range | Purpose |
|---|---|---|---|---|---|
| Geometry | Socket_0 | Geometry | (points) | — | Point cloud to instance onto |
| Collection | Socket_2 | Collection | — | — | Objects to scatter as instances |
| Scale Attribute | Socket_3 | String | "pscale" | — | Float attribute name for uniform scale |
| Rotation Attribute | Socket_4 | String | "orient" | — | Quaternion attribute name for rotation |
| Pick Instance | Socket_5 | Bool | true | — | Randomly select object per point |
| Seed | Socket_6 | Int | 0 | — | Randomness for instance picking |

## Internal structure

```
Group Input
  ├─ Scale Attribute ──→ Named Attribute (FLOAT)
  │   └─ Exists? → Switch: attr value / 1.0
  │       └─ Combine XYZ (uniform) ──→ Instance on Points.Scale
  │
  ├─ Rotation Attribute ──→ Named Attribute (QUATERNION)
  │   └─ Exists? → Switch: attr value / identity
  │       └─ Instance on Points.Rotation
  │
  ├─ Collection ──→ Collection Info (Separate Children, Reset Children)
  │                  └─ Instance on Points.Instance
  │
  ├─ Geometry ──→ Instance on Points.Points
  ├─ Pick Instance ──→ Instance on Points.Pick Instance
  ├─ Seed ──→ Random Value (INT, ID=Index) ──→ Instance on Points.Instance Index
  │
  └─ Instance on Points.Instances ──→ Group Output
```

## Composes with

- **SynthGen.Scatter on Surface** (upstream) — reads `pscale` and `orient`
  from scatter output. Wire scatter geometry → this asset's geometry input.
- **Material Override** (downstream) — reads `id` from scatter to drive
  per-instance material variation.
- **SynthGen container** — designed to work as a sub-group node inside the
  container, receiving geometry from the scatter sub-group.

## Limitations

- Uniform scale only (`pscale` → same X/Y/Z). Non-uniform `scale` vector
  attribute not yet supported.
- No LOD or proxy switching.
- Instance Index uses Random Value with max=100000; collections with more
  objects than that would need adjustment.

## Sweep guidance

For synthetic data variation, sweep:
- **Seed** — different instance assignments per image
- **Collection** — swap object sets for different scenes
- **Pick Instance** — false for single-object instancing, true for variety
