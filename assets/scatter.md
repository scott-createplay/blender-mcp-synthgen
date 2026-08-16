---
asset: Scatter on Surface
file: scatter.blend
node_group: Scatter on Surface
category: distribution
version: 0.2
blender: "5.2"
---

# Scatter on Surface

Distributes points across a mesh surface with per-element density control, exact
count mode, and well-known attribute output. Outputs a point cloud — instancing
is downstream.

## When to use

- Scatter points for vegetation, rocks, debris, or any repeating element
- Feed the output into Instance on Points (separate asset or user-wired)
- Drive spatial distribution with a painted/computed density attribute

Do NOT use when:
- You need precise manual placement
- You need volume-based distribution (use a volume scatter asset)

## Design intent

The scatter outputs a **point cloud with well-known attributes**, not instances.
Instancing is a separate concern. This follows the Houdini Scatter SOP model —
scatter produces points, Copy to Points / Instance is downstream.

**Attribute-centric:** The scatter communicates through named attributes, not
socket wiring. It reads `density` by name from upstream. It writes `pscale`,
`orient`, `N`, `id` on output points. Downstream assets and Instance on Points
read these attributes automatically.

**pscale passthrough:** The scatter does NOT overwrite upstream `pscale` by
default. If present upstream, it flows through untouched. Only when
`Randomize Scale` is explicitly enabled does the scatter write random values.
The scatter distributes points — it doesn't redefine their scale.

**Count mode:** Exact point count via oversample-and-trim. Computes a density
from `count / surface_area × 1.1`, scatters with RANDOM, then deletes points
with index >= target count.

## Read attributes

| Attribute | String parameter | Default name | Fallback |
|-----------|-----------------|--------------|----------|
| density weight | Density Attribute | `"density"` | 1.0 (uniform) |
| scale | Scale Attribute | `"pscale"` | 1.0 |

## Write attributes

| Attribute | Type | Domain | Source |
|-----------|------|--------|--------|
| `pscale` | FLOAT | POINT | Passthrough (or 1.0). Random when Randomize Scale = true. |
| `orient` | QUATERNION | POINT | Rotation from Distribute Points (normal alignment) |
| `N` | FLOAT_VECTOR | POINT | Surface normal at scatter point |
| `id` | INT | POINT | Sequential index per point |

## Parameters

| Name | Identifier | Type | Default | Range | Purpose |
|---|---|---|---|---|---|
| Geometry | Socket_0 | Geometry | (mesh) | — | Surface to scatter on |
| Density Attribute | Socket_2 | String | "density" | — | Float attribute name modulating density. Empty = uniform. |
| Density Max | Socket_3 | Float | 10.0 | 0.1–10000 | Ceiling on point density (pts/unit²) |
| Seed | Socket_4 | Int | 0 | — | Distribution randomness |
| Count | Socket_5 | Int | 100 | 1–1000000 | Target count (when Use Count = true) |
| Use Count | Socket_7 | Bool | false | — | true = count mode, false = density mode |
| Scale Attribute | Socket_8 | String | "pscale" | — | Attribute name for per-point scale |
| Scale Min | Socket_9 | Float | 0.8 | 0.01–10 | Min random scale (Randomize Scale only) |
| Scale Max | Socket_10 | Float | 1.2 | 0.01–10 | Max random scale (Randomize Scale only) |
| Randomize Scale | Socket_11 | Bool | false | — | true = overwrite scale attr with random |
| Relax Iterations | Socket_13 | Int | 0 | 0–10000 | Push-apart + snap-back passes; 0 = pure random |
| Scale Radii By | Socket_14 | Float | 1.0 | 0–2 | Multiplier on density-derived push radius |
| Max Relax Radius | Socket_16 | Float | 1.0 | 0.001–100 | Clamps push radius in near-zero density areas |

## Internal structure

```
Group Input
  ├─ Geometry ──→ Distribute Points on Faces (RANDOM, Mesh)
  │              ├─ also → Area Sum (for count mode)
  │
  ├─ Density Attribute ──→ Named Attribute (density lookup)
  │   └─ Exists? → Switch: attr value / 1.0
  │       └─ × Density Max ──→ Mode Switch (density path)
  │
  ├─ Count ──→ Count / Area Sum × 1.1 ──→ Mode Switch (count path)
  ├─ Use Count ──→ Mode Switch selector
  │
  │  Mode Switch output ──→ Distribute.Density
  │
  │  Distribute.Points ──→ [if Use Count]: Delete (Index >= Count)
  │                    ──→ Trim Gate (Use Count selects raw vs trimmed)
  │
  │  Trim Gate ──→ Repeat Zone (Relax Iterations passes):
  │                  ┌ Density-aware radius:
  │                  │  Named Attribute (density) → Switch (exists? : 1.0)
  │                  │  → Sample Nearest Surface (from input mesh)
  │                  │  → max(ε) → √ → 1/√ → min(Max Relax Radius)
  │                  │  → × Scale Radii By → × 0.05 damping → push_amount
  │                  ├ Nearest neighbor:
  │                  │  Index of Nearest (self-excluded) → Sample Index
  │                  │  → my_pos - neighbor_pos → normalize → × push_amount
  │                  ├ Set Position (Offset) → nudge apart
  │                  ├ Sample Nearest Surface → snap back to input mesh
  │                  └ Set Position → apply snapped position
  │               ──→ Store pscale (passthrough or random)
  │            ──→ Store orient (from Distribute.Rotation)
  │            ──→ Store N (from Distribute.Normal)
  │            ──→ Store id (from Index)
  │            ──→ Group Output
  │
  ├─ Scale Attribute ──→ pscale lookup + Store name
  ├─ Randomize Scale ──→ gates random vs passthrough
  ├─ Scale Min/Max ──→ Random Value (when randomize = true)
  └─ Seed ──→ Distribute.Seed
```

## Composes with

- **Instance on Points** — wire output geometry to Points input. pscale drives
  Scale (via Named Attribute → Combine XYZ), orient drives Rotation.
- **Density producers** — any upstream node that writes a `density` float
  attribute modulates the scatter distribution automatically.
- **Upstream pscale** — store `pscale` on the input mesh before scattering.
  The scatter reads it for future relaxation radii and passes it through to
  instancing. No re-wiring needed.

## Limitations

- Relaxation uses density-aware radii (1/√density, clamped by Max Relax Radius)
  with `Index of Nearest` (self-excluded) for neighbor finding, push + `Sample
  Nearest Surface` snap-back inside a Repeat Zone. Pure GN, no Python. At 20
  iterations on 50 points, uniformity reaches ~0.60 (vs 0.05 unrelaxed).
  Density-proportional radii preserve density gradients during relaxation —
  dense areas push less, sparse areas push more (per Houdini Scatter SOP model).
- No instancing — outputs raw point cloud. Wire Instance on Points downstream.
- Normal alignment only (Z-up oriented to face normal). No custom axis control.
- RANDOM distribution only. No Poisson mode.

## Sweep guidance

For synthetic data variation, sweep:
- **Seed** — different point arrangements per image
- **Density Max** or **Count** — sparse to dense coverage
- **Randomize Scale + Scale Min/Max** — size variation (opt-in)
- **Relax Iterations** — 0 (random) to 10–20 (blue noise)
- **Density Attribute** (via upstream) — spatial distribution patterns
