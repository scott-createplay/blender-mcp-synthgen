# POR — Round 2 hardening (field-feedback fixes)

## Problem

Second agent session — same task (18-node city_seed_scatter GN network on
Blender 5.2), now against the mutation-hardened server from dev_task 005.

**Outcome: the network works.** 33 instances scattered, attributes stored,
scene saved. But it took ~55 calls and three fallbacks. 6/10 round-1 items
confirmed fixed; 8 new issues remain, plus ordering constraints discovered
the hard way.

The single most costly problem was not a crash — it was that *working output
was invisible through the tools*. Viewport never repainted; `evaluate_object`
reported zeroes when 33 instances existed; `get_modifier_inputs` returned `[]`
when 15 parameters were present.

Source: `SYNTHGEN_MCP_FEEDBACK_ROUND2.md` from the agent that ran the session.

## Goal

Fix the 8 remaining issues so a realistic procedural session (18+ nodes,
34+ links, 15 exposed parameters) completes without fallbacks, with accurate
observability at every step.

## Decisions locked

- Same architecture — SSE + main-thread executor stays.
- Offline-testable first — pytest without Blender for code-generation checks.
- Backwards compatible — existing tool signatures don't break.
- Sidecar saves only.

## Stages

### Stage 1 — Viewport redraw after mutations (B)

**Priority: highest.** Everything the agent builds is invisible in the
user's viewport. The server mutates from a background thread; nothing calls
`area.tag_redraw()`, so Blender never repaints. The user concluded the MCP
was driving a different Blender.

#### 1.1 Tag redraw after mutating calls

After any call with `mutates=True`, iterate
`bpy.context.window_manager.windows → screen.areas → tag_redraw()`.
Inject this into `_run()` so all mutation tools get it automatically.

The code runs in the executor (main thread), so `bpy.context` is valid.
Add it to the generated Python code, not the transport layer.

**Validation:** Unit test confirms `tag_redraw` code is present in mutation
calls. Live test: verify viewport updates after `create_object` / `add_node`.

---

### Stage 2 — Truthful observability (C + D)

**Priority: high.** Two tools actively mislead by reporting "nothing here"
when things are fine.

#### 2.1 `evaluate_object` — report all geometry components

Current code only reports mesh component (verts/edges/faces). GN outputs
point clouds, instances, curves, and volumes. A scatter graph producing 33
instances shows as `verts: 0, faces: 0`.

**Fix:** After depsgraph eval, also report:
- `depsgraph.object_instances` count for instance-aware output
- Per-domain attributes (point, face, corner, edge, instance)
- Point cloud / curve component counts from `evaluated.data`

Target output shape:
```json
{"mesh": {"verts": 0, "faces": 0},
 "points": 33, "instances": 33, "curves": 0,
 "attributes": {"point": ["height", "width", "depth"], "mesh": [...]},
 "modifier_warnings": []}
```

#### 2.2 `get_modifier_inputs` — fix 5.x read path

Returns `[]` on Blender 5.2 even when inputs exist. The 5.x read path is:
```python
mod.properties.inputs["Socket_0"].to_dict()
# {'value': 220.0, 'type': 1, 'attribute_name': ''}
```

**Fix:** On `bpy.app.version >= (5, 0, 0)`, iterate
`mod.properties.inputs` and read `['value']` and `['attribute_name']`.
Surface `attribute_name` — it distinguishes literal values from
attribute-driven inputs.

**Validation:** Unit test confirms 5.x code path is generated with
`properties.inputs`. Live test with a modifier that has exposed parameters.

---

### Stage 3 — `build_graph` ordering + rollback + existing-tree lookup (A)

**Priority: high.** Three bugs, none survivable — the flagship compound tool
cannot build any graph with exposed parameters.

#### 3.1 Reorder: parameters → nodes → defaults → links

Group Input's output sockets ARE the interface. If parameters are created
after nodes, every link from GroupIn fails:
```
{"error": "output socket Ground Size X not found on GroupIn",
 "available": ["__extend__"]}
```

**Fix:** In the generated code, move parameter creation before node creation.
Order: tree creation → parameters → nodes → defaults → links → layout.

#### 3.2 Wire rollback on SystemExit

The docstring says rollback happens on failure, but `SystemExit` is caught
separately and does NOT delete the tree. After A1 fails, `graph_nodes` still
shows the tree with 16 nodes, zero links, zero parameters.

**Fix:** In the `except SystemExit` handler, check `created_tree` and remove
the tree if true (same logic as the generic `except Exception` handler).

#### 3.3 Seed name map from existing tree when `create_tree=false`

With `create_tree=false` and `nodes=[]`, the name map is empty. Any link
referencing existing nodes produces `KeyError: 'GroupIn'`.

**Fix:** When `create_tree=false`, iterate `tree.nodes` and populate
`node_map` from existing nodes before processing the `nodes` list.

**Validation:** Unit tests for each sub-issue:
- Parameters resolve in GroupIn links
- SystemExit triggers rollback
- Existing tree nodes are visible to links

---

### Stage 4 — `set_parameter` 5.x write path (E)

**Priority: high.** Blocks driving parameters, which blocks `sweep()`.

#### 4.1 Fix write path for 5.x

Current code uses `mod[socket_id] = value` which fails on 5.2:
```
Error: bpy_struct[key] = val: id properties not supported for this type
```

**Fix:** On `bpy.app.version >= (5, 0, 0)`, write via:
```python
mod.properties.inputs[socket_id]['value'] = value
```

**WARNING:** Do NOT use `bl_system_properties_get()` — it hangs Blender's
main thread with no exception, and recovery requires force-quit. This killed
the round-1 session.

**Validation:** Unit test confirms version-branching code. Live test: set a
parameter and read it back via `get_modifier_inputs`.

---

### Stage 5 — Polish (F + G + H)

#### 5.1 `expose_parameter` — coerce min/max for int sockets (F)

`default_value` int coercion works; `min_value` / `max_value` do not. JSON
has one number type, so any bounded int socket fails:
```
NodeTreeInterfaceSocketInt.min_value expected an int type, not float
```

**Fix:** Apply the same `int()` coercion to `min_value` and `max_value` when
`socket_type == "NodeSocketInt"`.

#### 5.2 Disabled sockets in error messages (G)

`link_sockets` reports `"'Distance Min' not found"` then lists it as
available. The socket exists but is disabled (mode-dependent — only active
in POISSON mode).

**Fix:** Filter the "available" list to enabled sockets, or append
`" (disabled)"` to disabled ones in the list. Optionally detect the mode
enum and suggest: `"'Distance Min' is disabled in distribute_method=RANDOM;
set it to POISSON first"`.

#### 5.3 Modifier default divergence (H)

Exposed parameter with `default: 0.01`; tree interface holds `0.01`;
modifier reads `0.31`. The modifier input is not initialized from the
interface default.

**Fix:** After `expose_parameter`, if the tree is bound to a modifier,
refresh the modifier's input to match the interface default. Use
`mod.properties.inputs[identifier]['value'] = default` on 5.x (same write
path as Stage 4).

#### 5.4 EEVEE engine ID in `configure_render` docstring

Docstring still advertises the 4.x `BLENDER_EEVEE_NEXT`. In 5.x the ID is
`BLENDER_EEVEE`. Update the docstring and add version-branching to the
validation if present.

**Validation:** Unit tests for int coercion of min/max, disabled socket
filtering, modifier default sync.

---

## Ordering constraints to encode

Discovered by the agent; encoding them removes most of the session friction:

1. **Node group + interface before modifier.** A modifier bound to a bare
   tree gets unset inputs → zero output.
2. **Node properties before mode-dependent socket links.** Mode-dependent
   sockets are disabled until the mode is set.
3. **Parameters before links** (always). Group Input outputs = interface.

`build_graph` handling (3) is Stage 3.1. Consider enforcing (1) in
`add_gn_modifier` and documenting (2) in `link_sockets` error messages.

---

## Mapping to feedback items

| Feedback | Stage | Step |
|---|---|---|
| A1 — links before params | 3 | 3.1 |
| A2 — no rollback | 3 | 3.2 |
| A3 — can't see existing nodes | 3 | 3.3 |
| B — viewport never redraws | 1 | 1.1 |
| C — evaluate_object mesh-only | 2 | 2.1 |
| D — get_modifier_inputs empty | 2 | 2.2 |
| E — set_parameter broken 5.x | 4 | 4.1 |
| F — int coercion min/max | 5 | 5.1 |
| G — disabled sockets listed | 5 | 5.2 |
| H — modifier default diverges | 5 | 5.3 |
