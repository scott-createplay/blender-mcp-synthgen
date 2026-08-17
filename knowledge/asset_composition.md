# Asset Composition — the container model

How synthgen assets compose inside Blender. Read `well_known_attributes.md` first — the
attribute contract is the data bus that makes composition work.

---

## 1. The Houdini mental model

In Houdini, a pipeline is a chain of SOPs inside a SOP context (a Geometry container at
the object level). Each SOP has its own parameter interface. You configure a SOP by diving
into it — you never promote every parameter from every SOP to the object level. Communication
between SOPs is through geometry attributes: Scatter writes `@pscale`, Copy to Points reads
`@pscale`. No explicit wiring.

Blender has no native equivalent of the SOP context. But **node group nesting** gives us
exactly the same thing.

## 2. The SynthGen container

A single **container node group** (name: "SynthGen" or pipeline-specific) acts as the SOP
context. It lives as a GN modifier on any object — the host object need not be a mesh.
The container is **geometry-agnostic**: it exposes Object reference inputs (hooks) that
source geometry via Object Info nodes. Swap the input object, the whole pipeline
recalculates. This mirrors Houdini's SOP context: the network has input connectors,
not an inherent geometry.

Its top-level interface is deliberately minimal:

- **Input hooks** — Object references (e.g., "Surface", "Collision") wired through
  Object Info → Geometry. Each hook sources geometry from an external object.
- **Seed** — master randomness (optional, assets can override)
- A handful of **global controls** relevant to the whole pipeline
- **Geometry out** — the processed result

Inside the container, individual assets are **sub-group nodes** — each one a self-contained
node group (SynthGen.Scatter on Surface, SynthGen.Instance on Points, etc.) wired in
sequence through the geometry stream.

```
[Any object — often an Empty as controller]
  └─ GN modifier → "SynthGen" container
       │
       │  Top-level interface (modifier panel):
       │    Surface (Object ref → Ground mesh)
       │    Seed, maybe Density Scale
       │
       │  Inside the container:
       │
       │  Group Input
       │    ├─ Surface ──→ Object Info ──→ Geometry
       │    │    └──→ [SynthGen.Scatter on Surface] ──→ [SynthGen.Instance on Points] ──→ ...
       │    └─ Seed ──→ (wired to sub-groups that need it)
       │
       │  ... ──→ [Material Override] ──→ Group Output
```

## 3. Parameters stay at the sub-group level

This is the critical design constraint. With 10 chained assets × 15 parameters each,
bubbling everything to the top-level container would create a 150-parameter modifier panel
with naming collisions and no structure.

Instead:

- **Each asset's parameters live on its own node group interface.** To configure the scatter,
  the user clicks the Scatter on Surface sub-group node and edits its parameters there — or
  the agent sets them via the MCP tools on that specific node group.
- **The container's modifier panel shows only global controls.** Seed, render quality,
  pipeline-level toggles.
- **No parameter promotion by default.** An asset's parameters are accessed by navigating
  into that asset's group, not from the parent.

The agent addresses a sub-group's parameter through the container: the modifier is on the
object, the node group is the container, and the sub-group node inside it exposes its own
inputs. The MCP path is: object → modifier → container group → sub-group node → input socket.

## 4. Attributes are the bus

Assets don't communicate through socket wiring between sub-groups (beyond the geometry
stream). They communicate through **well-known named attributes** carried on the geometry:

| Producer | Attribute | Consumer |
|----------|-----------|----------|
| Upstream mesh | `density` (FLOAT, FACE/POINT) | Scatter on Surface |
| Scatter on Surface | `pscale` (FLOAT, POINT) | Instance on Points |
| Scatter on Surface | `orient` (QUATERNION, POINT) | Instance on Points |
| Scatter on Surface | `N` (FLOAT_VECTOR, POINT) | Instance on Points, shaders |
| Scatter on Surface | `id` (INT, POINT) | Material Override, shaders, labels |
| Any asset | `Cd` (FLOAT_COLOR, POINT) | Shaders (attribute bridge) |

Each asset reads well-known attributes by name (via `Named Attribute` + `Exists` switch).
Each asset writes well-known attributes by name (via `Store Named Attribute`). The geometry
stream carries them between sub-groups automatically.

This is exactly how Houdini works — and it's why the attribute contract in
`well_known_attributes.md` matters. The attribute name IS the API between assets.

## 5. Before building: check Blender's built-in library

Blender ships a GN asset library (Generate, Mesh, Instances, Utilities, etc.)
visible in the Asset Browser under "Geometry Nodes." Before building any new
SynthGen asset, check this library first:

1. **Blender has it and it's sufficient** — skip. Use the built-in asset
   directly. Document that the pipeline expects the built-in, not a SynthGen
   version.
2. **Blender has it but it's missing something** — fork it. Add attribute-centric
   I/O (well-known attribute reads/writes, override pattern), register the
   modified version in the SynthGen catalog. Document what changed and why.
3. **Blender doesn't have it** — build from scratch following the contract below.

This check is step zero of every asset POR, not an afterthought.

## 6. What this means for asset authors

When building a new asset node group:

1. **Self-contained interface.** All parameters the user needs are Group Inputs on this
   node group. Sensible defaults, min/max ranges, clear names.
2. **Read well-known attributes.** Use `Named Attribute` with a string parameter (default =
   the well-known name). Gate with `Exists` → Switch so missing attributes fall back to
   built-in defaults. Never error on a missing attribute.
3. **Write well-known attributes.** Store outputs as named attributes on the geometry.
   Document what you write in the asset manifest.
4. **Geometry in, geometry out.** Accept geometry, produce geometry. The container wires
   the stream; the asset doesn't need to know what's upstream or downstream.
5. **Don't assume the container.** An asset should work standalone (as a direct modifier)
   or inside a container. The container is composition sugar, not a dependency.

## 7. Houdini → Blender mapping

| Houdini concept | Blender equivalent |
|---|---|
| SOP context (Geometry container) | Container node group (GN modifier) |
| Individual SOP | Sub-group node inside the container |
| SOP parameter interface | Node group interface (Group Inputs) |
| Dive into SOP | Click sub-group node / enter node group |
| Promote parameter to HDA | Expose sub-group input on container's Group Input (rare, only for globals) |
| `@attribute` communication | `Store Named Attribute` / `Named Attribute` with well-known names |
| HDA (Digital Asset) | Saved node group in a .blend library file |

## 8. What NOT to do

- **Don't bubble all parameters up.** 10 assets × 15 params = collision hell. Only global
  controls go to the top.
- **Don't use Object Info chains.** Earlier iteration — object referencing between modifiers.
  Replaced by the container model where everything is inside one node group.
- **Don't use the modifier stack for composition.** Stacking multiple GN modifiers on one
  object works for simple cases but loses the single-context model. The container keeps
  everything in one graph where you can see and wire the full pipeline.
- **Don't hardcode attribute names without the override pattern.** Always expose a string
  parameter so the user can redirect which attribute an asset reads from.
