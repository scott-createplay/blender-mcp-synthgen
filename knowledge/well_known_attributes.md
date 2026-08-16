# Well-Known Attributes

This document defines the attribute contract for the synthgen asset library.
Every asset reads and writes through named attributes following these conventions.
The attributes are the interface between assets — not the node group sockets.

Reference: https://www.sidefx.com/docs/houdini/model/attributes.html

## Design principle

Houdini nodes agree on a shared vocabulary of attribute names. When a scatter
writes `pscale`, a copy-to-points reads `pscale` — no explicit wiring needed.
The attribute name IS the API.

Blender GN has no equivalent convention. Node group sockets are explicit
connections, not shared state. We bridge this gap by establishing well-known
attribute names that every synthgen asset honors:

1. **Assets read from well-known attributes when they exist.** If `pscale` is
   present on input geometry, use it. If not, use the node's own default.
2. **Assets write well-known attributes as output.** The scatter stores the
   computed scale as `pscale`, the rotation as `orient`, etc.
3. **Users can override the attribute name.** Where a node reads a well-known
   attribute, the interface exposes a string parameter for the attribute name.
   The default is the well-known name, but the user can point it at any float,
   vector, or quaternion attribute they've computed upstream.

This makes composition automatic through the attribute bridge and gives the
user (or agent) explicit control over what drives each behavior.

## Attribute table

### Transform / Instancing

| Name | Type | Domain | Houdini equiv | Purpose |
|------|------|--------|---------------|---------|
| `pscale` | FLOAT | POINT | `@pscale` | Uniform scale per point/instance. Read by instancing assets to size instances. Default: 1.0. |
| `scale` | FLOAT_VECTOR | POINT | `@scale` | Non-uniform per-axis scale. Overrides `pscale` when present. |
| `orient` | QUATERNION | POINT | `@orient` | Full 3D rotation as quaternion. Primary rotation attribute for instancing. |
| `N` | FLOAT_VECTOR | POINT | `@N` | Surface normal. Used for orientation when `orient` is absent. Scatter writes this from the source surface. |
| `up` | FLOAT_VECTOR | POINT | `@up` | Up vector. Combined with `N` to define orientation when `orient` is absent. |
| `v` | FLOAT_VECTOR | POINT | `@v` | Velocity. Used for motion blur in rendering. Not computed automatically — must be set explicitly. |

**Rotation precedence** (matches Houdini):
1. `orient` quaternion (full control, no ambiguity)
2. `N` + `up` (orient-from-normal, tangent from up vector)
3. `N` alone (orient Z to normal, tangent is arbitrary)

### Identity / Organization

| Name | Type | Domain | Houdini equiv | Purpose |
|------|------|--------|---------------|---------|
| `id` | INT | POINT | `@id` | Unique identifier per element. Survives topology changes, reordering, deletion. Not the same as index. |
| `name` | STRING | FACE | `@name` | Named primitive group identifier. Use to find geometry by name in downstream processing. |
| `piece` | INT | FACE | `@piece` | Fragment/island identifier. Set by break-apart operations so downstream can tell which faces belong together. |

### Shading / Appearance

| Name | Type | Domain | Houdini equiv | Purpose |
|------|------|--------|---------------|---------|
| `Cd` | FLOAT_COLOR | POINT | `@Cd` | Diffuse color. Viewport displays this. Shaders read it via attribute bridge. |
| `Alpha` | FLOAT | POINT | `@Alpha` | Transparency. Combined with Cd for shading. |
| `uv` | FLOAT_VECTOR | CORNER | `@uv` | Texture coordinates. First two components are U, V. |
| `rest` | FLOAT_VECTOR | POINT | `@rest` | Rest position. Procedural textures sample this so patterns stick to the surface under deformation. |

### Scatter / Distribution

| Name | Type | Domain | Houdini equiv | Purpose |
|------|------|--------|---------------|---------|
| `density` | FLOAT | POINT/FACE | density attribute | Per-element density weight (0–1). Multiplies Density Max to control spatial distribution. |
| `source_prim` | INT | POINT | `@sourceprim` | Index of the source primitive the point was scattered on. Set by scatter, used for attribute interpolation. |
| `source_uv` | FLOAT_VECTOR | POINT | `@sourceprimuv` | Parametric UV on the source primitive. Used with attribute interpolation to recover source surface properties. |

## The override pattern

Where an asset reads a well-known attribute, the interface should expose a
string parameter with the well-known name as the default. This lets the user
redirect the behavior to any attribute they've computed upstream.

Example for the scatter asset:

```
Density Attribute  (string, default "density")
Scale Attribute    (string, default "pscale")
```

When the string is the default (`"density"`), the asset reads the well-known
attribute. When the user changes it to `"slope_weight"` or `"custom_mask"`,
the asset reads that attribute instead. When the string is empty, the asset
uses its own built-in default value (uniform density, scale = 1, etc.).

This gives three levels of control:
1. **Convention** — leave defaults, everything just works between assets
2. **Override** — point at a custom attribute for specific needs
3. **Disable** — clear the string, fall back to the node's own value

## Blender GN implementation

In Blender GN, well-known attributes are stored and read using:

- **Write:** `Store Named Attribute` node (GeometryNodeStoreNamedAttribute)
  with the well-known name as a string, the appropriate data_type, and domain.
- **Read:** `Named Attribute` node (GeometryNodeInputNamedAttribute) with the
  attribute name from the string parameter. The `Exists` output gates a Switch
  node: if the attribute exists, use its value; if not, use the built-in default.

The attribute names use Houdini conventions (lowercase, short) rather than
Blender conventions (which has no conventions for user attributes). This keeps
the mental model consistent for users coming from Houdini and gives the asset
library a coherent identity.

## What assets must do

Every synthgen asset should:

1. **Document which well-known attributes it reads and writes** in its manifest.
2. **Expose string parameters for attribute name overrides** on any well-known
   attribute it reads, with the well-known name as the default.
3. **Write well-known attributes on output geometry** so downstream assets can
   consume them without explicit wiring.
4. **Handle missing attributes gracefully** — if a well-known attribute is not
   present on input, fall back to the node's built-in default. Never error on
   a missing attribute.
5. **Use the correct data_type and domain** as specified in the table above.
   A `pscale` stored as FLOAT_VECTOR or on the FACE domain will silently break
   downstream consumers.
