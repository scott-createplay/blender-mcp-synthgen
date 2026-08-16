---
asset: Scatter on Surface
file: scatter.blend
node_group: Scatter on Surface
category: distribution
version: 0.1
blender: "5.2"
---

# Scatter on Surface

Distributes instances from a collection across a mesh surface using Poisson disk sampling, with per-point density control, random scale variation, and automatic normal alignment.

## When to use

- Scatter vegetation, rocks, debris, or any repeating element across terrain or surfaces
- Populate a surface with varied instances for synthetic data generation
- Any scenario where you need controllable, sweepable instance distribution

Do NOT use when:
- You need precise manual placement (use direct object placement instead)
- Instance orientation needs to follow a custom vector field rather than surface normals (extend this asset or build a custom graph)
- You need instances distributed in a volume rather than on a surface (use the SDF scatter asset)

## Design intent

Poisson over Random distribution because even spacing with a minimum distance constraint produces more natural-looking scatter, which matters for photorealistic synthetic data. Random distribution clusters and leaves gaps that read as artificial under rendering.

The density is controlled by two parameters working together: Density sets the ceiling, Density Factor multiplies it per-point. This separation lets the agent (or user) paint or compute a spatial mask without touching the global density — critical for workflows like "dense grass on flat areas, sparse on slopes" where the mask is derived from surface properties.

Scale randomization uses a single float mapped to uniform XYZ so instances scale proportionally. Non-uniform scale (stretch/squash) is intentionally omitted — it's a separate concern that belongs in a deformation asset or a per-instance modifier.

Pick Instance is enabled with a random index so the system automatically varies which collection child gets placed at each point. The agent doesn't need to manage instance selection.

## Parameters

| Name | Identifier | Type | Default | Range | Purpose |
|---|---|---|---|---|---|
| Geometry | Socket_0 | Geometry | (mesh) | — | Surface to scatter on. Automatically receives the modifier object's mesh. |
| Collection | Socket_1 | Collection | — | — | Collection of objects to instance. Each child is a candidate; the system picks randomly per point. |
| Density | Socket_2 | Float | 10.0 | 0.1–10000 | Maximum point density (points per unit area). Higher = more instances. |
| Density Factor | Socket_3 | Float | 1.0 | 0–1 | Per-point density multiplier. Set to a constant for uniform density, or toggle to attribute mode and specify a named attribute for spatial masking. |
| Scale Min | Socket_4 | Float | 0.8 | 0.01–10 | Minimum uniform scale factor per instance. |
| Scale Max | Socket_5 | Float | 1.2 | 0.01–10 | Maximum uniform scale factor per instance. |
| Seed | Socket_6 | Int | 0 | — | Controls point distribution randomness. Change to get a different arrangement. |
| Distance Min | Socket_8 | Float | 0.2 | 0.01–10 | Minimum distance between scattered points (Poisson disk radius). Increase for sparser, more even spacing. Must be > 0. |

## Internal structure

```
Group Input
  ├─ Geometry ──→ Distribute Points on Faces (Mesh)
  ├─ Density ──→ Distribute Points on Faces (Density Max)
  ├─ Density Factor ──→ Distribute Points on Faces (Density Factor)
  ├─ Distance Min ──→ Distribute Points on Faces (Distance Min)
  ├─ Seed ──→ Distribute Points on Faces (Seed)
  ├─ Collection ──→ Collection Info (Separate Children, Reset Children)
  ├─ Scale Min ──→ Random Value [float] (Min)
  └─ Scale Max ──→ Random Value [float] (Max)

Distribute Points on Faces (Poisson mode)
  ├─ Points ──→ Instance on Points (Points)
  └─ Rotation ──→ Instance on Points (Rotation)

Collection Info ──→ Instance on Points (Instance, Pick Instance = true)
Random Value [float] ──→ Combine XYZ (uniform) ──→ Instance on Points (Scale)
Random Value [int, seed=2] ──→ Instance on Points (Instance Index)

Instance on Points ──→ Group Output (Geometry)
```

## Composes with

- **Noise Displacement** — apply displacement first, then scatter on the deformed surface for vegetation on rough terrain
- **Attribute painting / weight maps** — compute or paint a float attribute, feed it into Density Factor for spatial control
- **Material assignment** — assign materials to the collection objects before scattering; they carry through to instances

## Limitations

- Normal alignment only (Z-up instances oriented to face normal). No custom orientation vector or alignment axis control.
- Uniform scale only. No per-axis scale variation.
- No rotation randomization around the normal axis — instances all face the same way relative to the surface tangent.
- The random index for Pick Instance uses a fixed seed offset (seed=2), independent of the main Seed parameter. Changing Seed re-distributes points but doesn't change which instance appears at each point.

## Sweep guidance

For synthetic data variation, the most impactful parameters to sweep are:
- **Seed** — different point arrangements per image
- **Density** — sparse to dense coverage
- **Scale Min / Scale Max** — size variation range
- **Density Factor** (via attribute) — spatial distribution patterns
