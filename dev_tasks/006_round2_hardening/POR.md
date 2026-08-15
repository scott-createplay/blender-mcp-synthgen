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

Source feedback:
`C:\Users\scooter\dev\__projects__\blender_camera_distribution_pkg\tools\SYNTHGEN_MCP_FEEDBACK_ROUND2.md`
(read this file for full context, raw error output, and the agent's suggested
fixes).

## Starting point

Branch from `dev/005-mutation-hardening` (commit `0601fb8`). That branch has
the auto-layout tool, /health version fields, deploy tooling, and all 005
mutation hardening work. Create a new branch `dev/006-round2-hardening`.

Key files:
- `src/synthgen/mcp/tools/blender.py` — mutation tools, `_run()`, `build_graph`
- `src/synthgen/mcp/tools/verify.py` — `evaluate_object`, `get_modifier_inputs`, `list_tree_nodes`
- `src/synthgen/mcp/tools/pipeline.py` — `set_parameter`, `sweep`
- `tests/test_mutation_hardening.py` — existing tests (267 passing)

Deploy + validate after changes:
```
python tools/deploy_addon.py       # kills Blender, copies addon + src + schemas
python tools/validate_addon.py     # health, SSE, MCP tool call
```

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

### Stage 1 — Viewport redraw after mutations (feedback B)

**Priority: highest.** Everything the agent builds is invisible in the
user's viewport. The server mutates from a background thread; nothing calls
`area.tag_redraw()`, so Blender never repaints. The user concluded the MCP
was driving a different Blender.

#### 1.1 Tag redraw after mutating calls

**File:** `src/synthgen/mcp/tools/blender.py` — `_run()` helper (~line 42)

After any call with `mutates=True`, append a redraw snippet to the
generated Python code:
```python
for _w in bpy.context.window_manager.windows:
    for _a in _w.screen.areas:
        _a.tag_redraw()
```

This runs in the executor (main thread), so `bpy.context` is valid. Add it
to the code string inside `_run()`, not the transport layer. Guard with
`try/except` since `bpy.context.window_manager` may be None in headless mode.

**Validation:** Unit test confirms `tag_redraw` code is present in generated
code when `mutates=True` and absent when `mutates=False`.

---

### Stage 2 — Truthful observability (feedback C + D)

**Priority: high.** Two tools actively mislead by reporting "nothing here"
when things are fine.

#### 2.1 `evaluate_object` — report all geometry components

**File:** `src/synthgen/mcp/tools/verify.py` — `evaluate_object` (~line 157)

Current code only checks `eval_obj.data` with `hasattr(eval_obj.data,
'vertices')` — mesh component only. GN outputs point clouds, instances,
curves, and volumes. A scatter graph producing 33 instances shows as
`verts: 0, faces: 0`.

**Fix:** After depsgraph eval, also report:
- Instance count from `sum(1 for _ in dg.object_instances if i.parent == eval_obj)` or similar
- Per-domain attributes: iterate `eval_obj.data.attributes` and group by `attr.domain`
- Check for point cloud data (`hasattr(eval_obj.data, 'points')`)

Target output shape:
```json
{"mesh": {"verts": 0, "faces": 0},
 "points": 33, "instances": 33, "curves": 0,
 "attributes": {"point": ["height", "width", "depth"], "mesh": [...]},
 "modifier_warnings": []}
```

Keep `warnings: []` — it was confirmed useful.

#### 2.2 `get_modifier_inputs` — fix 5.x read path

**File:** `src/synthgen/mcp/tools/verify.py` — `get_modifier_inputs` (~line 66)

⚠ **A 005 fix exists but uses the WRONG access pattern.** The current code
(lines 89-101) uses:
```python
for name in dir(mod.properties.inputs):       # WRONG
    inp = getattr(mod.properties.inputs, name)  # WRONG
    inp.default_value                            # WRONG
```

This returns `[]` on 5.2. The field agent confirmed the correct API is:
```python
mod.properties.inputs["Socket_0"].to_dict()
# {'value': 220.0, 'type': 1, 'attribute_name': ''}
```

**Fix:** Replace the 5.x branch. Iterate the tree interface to get socket
identifiers, then read values via bracket access:
```python
for item in mod.node_group.interface.items_tree:
    if hasattr(item, 'identifier') and item.in_out == 'INPUT':
        ident = item.identifier
        prop = mod.properties.inputs[ident]
        value = prop['value']
        attr_name = prop.get('attribute_name', '')
```

Surface `attribute_name` — it distinguishes a literal value from an
attribute-driven input.

**Validation:** Unit test confirms `properties.inputs[` bracket access in
generated code (NOT `getattr`). Live test with a modifier that has exposed
parameters.

---

### Stage 3 — `build_graph` ordering + rollback + existing-tree lookup (feedback A)

**Priority: high.** Three bugs, none survivable — the flagship compound tool
cannot build any graph with exposed parameters.

**File:** `src/synthgen/mcp/tools/blender.py` — `build_graph` (~line 503)

#### 3.1 Reorder: parameters → nodes → defaults → links

Group Input's output sockets ARE the interface. If parameters are created
after nodes (current order: nodes → links → parameters → defaults), every
link from GroupIn fails:
```
{"error": "output socket Ground Size X not found on GroupIn",
 "available": ["__extend__"]}
```

**Fix:** Reorder the code generation blocks in `build_graph`:
tree creation → **parameters** → nodes → defaults → links → layout.

Currently the order in the code is (check lines ~605-660):
1. Tree creation/lookup (~line 587)
2. Create nodes (~line 605)
3. Create links (~line 612)
4. Expose parameters (~line 628)
5. Set defaults (~line 651)
6. Auto-layout
7. Build result JSON

Change to: 1 → 4 → 2 → 5 → 3 → 6 → 7.

#### 3.2 Wire rollback on SystemExit

The `except SystemExit` handler (~line 677) just passes — it does NOT
delete the tree. After a link failure, `graph_nodes` shows the tree with
all nodes present, zero links, zero parameters.

**Fix:** Mirror the `except Exception` handler:
```python
except SystemExit:
    if created_tree:
        try:
            bpy.data.node_groups.remove(tree)
        except Exception:
            pass
```

#### 3.3 Seed name map from existing tree when `create_tree=false`

The `node_map` dict (~line 603) is only populated from newly created nodes.
With `create_tree=false` and `nodes=[]`, any link referencing existing nodes
(e.g. `GroupIn`, `GroupOut`) produces a bare `KeyError`.

**Fix:** After tree lookup when `create_tree=false`, add:
```python
for _existing in tree.nodes:
    node_map[_existing.name] = _existing
```

**Validation:** Unit tests for each sub-issue:
- Test that parameters code block appears before links code block
- Test that SystemExit handler includes `node_groups.remove`
- Test that `create_tree=false` generates code to seed node_map from existing

---

### Stage 4 — `set_parameter` 5.x write path (feedback E)

**Priority: high.** Blocks driving parameters, which blocks `sweep()`.

**File:** `src/synthgen/mcp/tools/pipeline.py` — `set_parameter` (~line 56)

⚠ **A 005 fix exists but uses the WRONG access pattern.** The current code
(lines 85-92) uses:
```python
inp = getattr(mod.properties.inputs, socket_identifier, None)  # WRONG
inp.default_value = value                                        # WRONG
```

Same misfire as Stage 2.2. The field agent confirmed the correct API:
```python
mod.properties.inputs[socket_identifier]['value'] = value
```

Also fix the same pattern in `sweep()` (~line 237) which has the same
broken `getattr` + `.default_value` pattern.

**WARNING:** Do NOT use `bl_system_properties_get()` — it hangs Blender's
main thread with no exception, and recovery requires force-quit. This killed
the round-1 session.

**Validation:** Unit test confirms bracket access `properties.inputs[` in
generated code (NOT `getattr`). Live test: set a parameter and read it back
via the fixed `get_modifier_inputs`.

---

### Stage 5 — Polish (feedback F + G + H)

#### 5.1 `expose_parameter` — coerce min/max for int sockets (F)

**File:** `src/synthgen/mcp/tools/blender.py` — `expose_parameter` (~line 1018)
and also the `build_graph` parameter block (~line 628)

`default_value` int coercion works; `min_value` / `max_value` do not. JSON
has one number type, so any bounded int socket fails:
```
NodeTreeInterfaceSocketInt.min_value expected an int type, not float
```

**Fix:** Apply `int()` coercion to `min_value` and `max_value` when
`socket_type == "NodeSocketInt"`. Check both `expose_parameter` standalone
and the parameter loop inside `build_graph`.

#### 5.2 Disabled sockets in error messages (G)

**File:** `src/synthgen/mcp/tools/blender.py` — `link_sockets` (~line 863)
and `build_graph` link block (~line 612)

`link_sockets` reports `"'Distance Min' not found"` then lists it as
available. The socket exists but is disabled (mode-dependent — only active
in POISSON mode).

**Fix:** In the "available" lists, filter or annotate disabled sockets.
Detect via `socket.enabled` property. Either:
- Filter: `[s.identifier for s in node.inputs if s.enabled]`
- Or annotate: `[s.identifier + (" (disabled)" if not s.enabled else "") ...]`

The annotated approach is better — it tells the agent *why* the socket
wasn't found and suggests setting the mode first.

#### 5.3 Modifier default divergence (H)

**File:** `src/synthgen/mcp/tools/blender.py` — `expose_parameter` (~line 1018)

Exposed parameter with `default: 0.01`; tree interface holds `0.01`;
modifier reads `0.31`. The modifier input is not initialized from the
interface default.

**Fix:** After creating the interface socket in `expose_parameter`, find
any modifiers using this tree and sync the input value:
```python
for obj in bpy.data.objects:
    for mod in obj.modifiers:
        if getattr(mod, 'node_group', None) == tree:
            mod.properties.inputs[sock.identifier]['value'] = default
```

Use the bracket write path from Stage 4.

#### 5.4 EEVEE engine ID in `configure_render` docstring

**File:** `src/synthgen/mcp/tools/blender.py` — `configure_render`

Docstring still advertises the 4.x `BLENDER_EEVEE_NEXT`. In 5.x the ID is
`BLENDER_EEVEE`. Update the docstring. If the tool validates the engine
parameter, add version-branching.

**Validation:** Unit tests for int coercion of min/max, disabled socket
filtering/annotation, modifier default sync code generation.

---

## Ordering constraints to encode

Discovered by the agent; encoding them removes most of the session friction:

1. **Node group + interface before modifier.** A modifier bound to a bare
   tree gets unset inputs → zero output.
2. **Node properties before mode-dependent socket links.** Mode-dependent
   sockets are disabled until the mode is set.
3. **Parameters before links** (always). Group Input outputs = interface.

`build_graph` handling (3) is Stage 3.1. Consider enforcing (1) in
`add_gn_modifier` and documenting (2) in `link_sockets` error messages
(partially addressed by Stage 5.2).

---

## Mapping to feedback items

| Feedback | Stage | Step | File |
|---|---|---|---|
| A1 — links before params | 3 | 3.1 | `blender.py` |
| A2 — no rollback | 3 | 3.2 | `blender.py` |
| A3 — can't see existing nodes | 3 | 3.3 | `blender.py` |
| B — viewport never redraws | 1 | 1.1 | `blender.py` |
| C — evaluate_object mesh-only | 2 | 2.1 | `verify.py` |
| D — get_modifier_inputs empty | 2 | 2.2 | `verify.py` |
| E — set_parameter broken 5.x | 4 | 4.1 | `pipeline.py` |
| F — int coercion min/max | 5 | 5.1 | `blender.py` |
| G — disabled sockets listed | 5 | 5.2 | `blender.py` |
| H — modifier default diverges | 5 | 5.3 | `blender.py` |

## 005 fixes that need correction

Two items from dev_task 005 shipped with the **wrong Blender 5.x API access
pattern** and must be fixed in this task:

| Tool | 005 code (broken) | Correct 5.2 API |
|---|---|---|
| `get_modifier_inputs` | `getattr(mod.properties.inputs, name).default_value` | `mod.properties.inputs[ident]['value']` |
| `set_parameter` | `getattr(mod.properties.inputs, sid).default_value = v` | `mod.properties.inputs[sid]['value'] = v` |
| `sweep()` inner loop | same `getattr` pattern | same bracket pattern |

The `dir()` + `getattr()` approach returns nothing because `properties.inputs`
members are not Python attributes — they are RNA properties accessed via
bracket/subscription syntax. The tree interface provides the identifiers;
bracket access on `properties.inputs` provides the values.
