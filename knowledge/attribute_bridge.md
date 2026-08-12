# The Attribute Bridge — connecting Geometry Nodes ↔ Shading

**Grounded against Blender 5.2.0 LTS** (`blender_gn_schema.json`, `blender_shader_schema.json`).
Verify any node/socket here with `python query_schema.py [--shader] show "<node>"`.

This is the spine of the synthetic-data pipeline. Geometry Nodes create **structure and
variation**; shaders create **appearance variation**; **named attributes** are the only wire
between them. Master this and one material can paint thousands of per-instance-varied
looks — no material duplication, and the same mechanism carries ground-truth labels.

---

## The one-paragraph mental model

A **named attribute** is a typed value stored per-element on a **domain** (`POINT`, `EDGE`,
`FACE`, `CORNER`, `CURVE`, `INSTANCE`, `LAYER`). Geometry Nodes **writes** it
(`Store Named Attribute`); the shader **reads** it (`Attribute` node). They must agree on
three things: **name** (exact string), **data type** (float/vector/color/int), and **which
domain the reader is looking at** (`GEOMETRY` vs `INSTANCER`). Get those three aligned and
the bridge works; mismatch any one and you get zeros or garbage — silently, with no error.

---

## The two halves (verified sockets)

### Write side — Geometry Nodes
`GeometryNodeStoreNamedAttribute` — inputs `(Geometry, Selection, Name, Value)` → `(Geometry)`
- `data_type` ∈ `FLOAT, INT, BOOLEAN, FLOAT_VECTOR, FLOAT_COLOR, QUATERNION, FLOAT4X4, STRING, INT8, INT16_2D, INT32_2D, FLOAT2, FLOAT4, BYTE_COLOR`
- `domain` ∈ `POINT, EDGE, FACE, CORNER, CURVE, INSTANCE, LAYER`
- ⚠️ **Set `data_type` first, then link `Value`.** The active `Value` socket's type follows
  `data_type`; if you link before setting it, you wire the wrong typed socket.

### Read side — Shader
`ShaderNodeAttribute` — no inputs → outputs `(Color[RGBA], Vector[VECTOR], Fac[VALUE], Alpha[VALUE])`
- `attribute_type` ∈ `GEOMETRY, OBJECT, INSTANCER, VIEW_LAYER`
- ⚠️ The attribute **name is a string property, not a socket**: `node.attribute_name = "rust"`.
- ⚠️ The scalar output identifier is **`Fac`** (UI label "Factor").
- **Pick the output that matches the stored type:** scalar→`Fac`, vector→`Vector`, color→`Color`.

---

## `attribute_type` — the decision that trips everyone

| Reader `attribute_type` | Reads from | Use when |
|---|---|---|
| `INSTANCER` | the **instancing** geometry's point/instance domain | geometry is **instanced** (Instance on Points) and you want **per-instance** variation |
| `GEOMETRY`  | the mesh's own POINT/CORNER/etc domain | attributes live on **realized** mesh geometry (after `Realize Instances`) |
| `OBJECT`    | the object's own attributes / properties | per-object values shared by the whole object |
| `VIEW_LAYER`| render/view-layer globals | rarely, for scene-level values |

**The single most common failure:** storing on `INSTANCE` domain, then reading with
`GEOMETRY` (returns nothing), or reading with `INSTANCER` **after** `Realize Instances`
(instances no longer exist → nothing). Rule of thumb:

- **Still instanced** at output → shader reads `INSTANCER`.
- **Realized** before output → shader reads `GEOMETRY`.

---

## How attributes propagate through instancing (the subtle part)

1. Attributes on the **points** feeding `Instance on Points` become readable on the resulting
   instances via `attribute_type = INSTANCER`. So the easiest per-instance variation is to
   store on the **points before instancing** (domain `POINT`).
2. To set/override **after** instancing, `Store Named Attribute` with **`domain = INSTANCE`**
   on the `Instances` stream.
3. `Realize Instances` bakes instances into one mesh; instance attributes transfer onto the
   realized geometry → switch the shader reader to `GEOMETRY`. (Realizing kills the memory
   win of instancing — avoid it for large synthetic batches unless you need per-vertex ops.)

---

## Canonical recipes (conceptual graphs — build with the verified IDs)

### 1. Per-instance color variation (one material, N colors)
```
GN:   points ─▶ Store Named Attribute[data_type=FLOAT_COLOR, domain=POINT, Name="inst_col",
                    Value ◀ Random Value[data_type=FLOAT_COLOR]] ─▶ Instance on Points ─▶ output
Shd:  Attribute[attribute_type=INSTANCER, attribute_name="inst_col"].Color ─▶ Principled.Base Color
```

### 2. Per-instance scalar → material param (e.g. rust / wear / roughness)
```
GN:   Store Named Attribute[FLOAT, POINT, "rust", Value ◀ Random Value[FLOAT, min=0,max=1, Seed]]
Shd:  Attribute[INSTANCER,"rust"].Fac ─▶ Map Range ─▶ Principled.Roughness (or mix two textures)
```

### 3. Segmentation / class ID (ground-truth labels ride the SAME bridge)
```
GN:   Store Named Attribute[INT, POINT/INSTANCE, "class_id", Value ◀ integer per class]
Out:  read "class_id" for masks via  (a) Set Material Index + per-class AOV material,
      or (b) a dedicated ID pass. Synthetic data = RGB *plus* labels; both are attributes.
```

### 4. Per-object (not per-instance) variation — cheaper channel
```
Shd:  Object Info.Random ─▶ Map Range / Color Ramp ─▶ any param   # varies per object, free, no GN write
```

---

## Data-type matching cheat-sheet

| Want to vary | GN store `data_type` | Shader `Attribute` output |
|---|---|---|
| color | `FLOAT_COLOR` | `Color` |
| scalar (0–1, angle, mask) | `FLOAT` | `Fac` |
| direction / 3-vector | `FLOAT_VECTOR` | `Vector` |
| integer class id | `INT` | `Fac` (rounds) or via Material Index |

---

## Gotchas checklist (all verified against 5.2)

- [ ] Shader `Attribute` name is `node.attribute_name`, **not** an input socket.
- [ ] Scalar output is `Fac` (label "Factor"), not "Value".
- [ ] Set GN `Store` `data_type` **before** linking `Value`.
- [ ] `INSTANCER` only while instanced; `GEOMETRY` after `Realize Instances`.
- [ ] Reader domain must match where you wrote (POINT before instancing ≈ INSTANCER after).
- [ ] Name string must match **exactly** (case-sensitive).
- [ ] Confirm the attribute exists: GN `Named Attribute("name")` has an **`Exists`** boolean output — use it in the verify step.

---

## Verify step (fold into the build→verify loop)

After wiring a bridge, don't trust it — check it:
1. In GN, tap `Named Attribute[name].Exists` → Viewer, or read domain size, to confirm the
   attribute was actually written on the expected domain.
2. Render a **small batch** (e.g. 16 instances) and confirm the variation is visible and
   spans the intended range (not all identical = broken bridge; identical usually means
   wrong `attribute_type` or domain mismatch).
3. Only then scale the batch up.
