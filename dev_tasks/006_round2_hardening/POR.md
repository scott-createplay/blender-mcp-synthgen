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
- `addon/synthgen_mcp/server.py` — MCP server, `/health`, server instructions
- `addon/synthgen_mcp/executor.py` — transport, `MainThreadExecutor`, version detection
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
- **Host-side version routing** — Blender version cached on transport at
  startup, used at code-gen time. No `if bpy.app.version` in generated code.
  MCP server instructions are dynamic and include version + API mode, injected
  every turn so the agent always knows which version it's connected to.

## Stages

### Stage 0 — Version routing infrastructure

**Priority: foundation.** Stages 2, 4, and 5 depend on this. Without it,
every version-dependent fix is another inline `if bpy.app.version` branch
embedded in generated code strings.

#### Architectural decision

The Blender version is detected once at startup via `/health` and cached on
the host-side transport. Structured tools query the cached version at
**code-generation time** and emit clean, branchless Python for the target
version. The MCP server's `instructions` field is made dynamic to include the
connected version and API mode — this is injected into the agent's context on
every turn by the MCP protocol, surviving context compression in long chats.

This means:
- Generated code is native to the target version (works as a standalone script).
- The agent cannot hallucinate cross-version API calls in structured tools.
- `execute_python` (the ungrounded escape hatch) gets version guidance via the
  dynamic instructions — probabilistic, not enforced, but sufficient.

#### 0.1 Cache Blender version on transport

**File:** `addon/synthgen_mcp/server.py`

The version is already read at startup (`_blender_version`). Expose it so that
tool code-gen functions can query it:

```python
def get_blender_version_tuple() -> tuple[int, ...]:
    """Cached Blender version as (major, minor, patch)."""
    ...
```

Tools import and call this to decide which code path to emit.

#### 0.2 Dynamic MCP server instructions

**File:** `addon/synthgen_mcp/server.py`

Replace the static `instructions` string with a dynamic one built at startup
that includes:

```
Connected to Blender {major}.{minor}.{patch}.
API mode: 5.x — bracket access on properties.inputs,
compositing_node_group for compositor, engine ID BLENDER_EEVEE.
```

(Or the 4.x equivalents if `major < 5`.)

This appears in the agent's system context on every turn.

#### 0.3 Version-aware code-gen helpers

**File:** `src/synthgen/mcp/tools/compat.py` (new)

Thin helper functions that emit version-correct **code snippets** (strings),
not runtime adapters. Used by structured tools at code-gen time:

```python
def emit_read_input(ver, mod_var, ident_expr):
    """Return code string to read a modifier input value."""
    if ver >= (5, 0, 0):
        return f"{mod_var}.properties.inputs[{ident_expr}]['value']"
    return f"{mod_var}[{ident_expr}]"

def emit_write_input(ver, mod_var, ident_expr, value_expr):
    """Return code string to write a modifier input value."""
    ...

def emit_iter_inputs(ver, mod_var, tree_var):
    """Return code block that yields (identifier, value, attr_name)."""
    ...

def emit_compositor_tree(ver, scene_var):
    """Return expression string for the compositor node tree."""
    ...

def eevee_engine_id(ver):
    """Return the correct EEVEE engine string constant."""
    ...
```

These are pure functions: `(version_tuple, ...) → str`. No bpy import, no
Blender dependency. Fully testable offline.

#### 0.4 Migrate existing version branches

Replace all inline `if bpy.app.version >= (5, 0, 0)` blocks in generated code
with calls to the compat helpers. After this step, generated code strings
contain zero version branches — they are clean Python for the target version.

**Files affected:**
- `src/synthgen/mcp/tools/pipeline.py` — `set_parameter`, `sweep`
- `src/synthgen/mcp/tools/verify.py` — `get_modifier_inputs`
- `src/synthgen/mcp/tools/blender.py` — compositor tree lookups

**Validation:** Existing tests pass. New unit tests confirm:
- Compat helpers emit correct code for 4.x and 5.x inputs.
- No generated code contains `bpy.app.version`.
- MCP server instructions include version string.

---

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

**Uses Stage 0 compat helpers.** Replace the inline version branching with
calls to `emit_iter_inputs()` / `emit_read_input()`. The generated code
uses bracket access on 5.x, `mod[ident]` on 4.x — no runtime branch.

⚠ **The 005 fix uses the WRONG access pattern.** The current code uses
`dir()` + `getattr()` + `.default_value` — returns `[]` on 5.2. The correct
5.x API is `mod.properties.inputs[ident]['value']` with identifiers from
`mod.node_group.interface.items_tree`.

Surface `attribute_name` — it distinguishes a literal value from an
attribute-driven input.

**Validation:** Unit test confirms bracket access `properties.inputs[` in
generated code for 5.x (NOT `getattr`). Confirms `mod[` for 4.x.

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

**Uses Stage 0 compat helpers.** Replace the inline version branching with
calls to `emit_write_input()`. The generated code uses bracket write on 5.x,
`mod[ident] = v` on 4.x — no runtime branch.

⚠ **The 005 fix uses the WRONG access pattern.** The current code uses
`getattr` + `.default_value` — same misfire as Stage 2.2.

Also fix the same pattern in `sweep()` (~line 237) which has the same
broken `getattr` + `.default_value` pattern.

**WARNING:** Do NOT use `bl_system_properties_get()` — it hangs Blender's
main thread with no exception, and recovery requires force-quit. This killed
the round-1 session.

**Validation:** Unit test confirms bracket access `properties.inputs[` in
generated code for 5.x (NOT `getattr`). Confirms `mod[` for 4.x.

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
any modifiers using this tree and sync the input value. **Uses Stage 0
compat helpers** for the write path (`emit_write_input`).

#### 5.4 EEVEE engine ID in `configure_render` docstring

**File:** `src/synthgen/mcp/tools/blender.py` — `configure_render`

Docstring still advertises the 4.x `BLENDER_EEVEE_NEXT`. **Uses Stage 0
`eevee_engine_id()`** to document the correct ID for the connected version.
If the tool validates the engine parameter, add version-aware validation.

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
| (infrastructure) | 0 | 0.1–0.4 | `server.py`, `compat.py`, all tools |
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

---

## Progress

### Stage 0 — COMPLETE (2026-08-15)

All sub-steps delivered and validated (296 tests, 0 failures).

**0.1 — compat.py:** Created `src/synthgen/mcp/tools/compat.py` with 5 pure
helper functions (`emit_read_input`, `emit_write_input`, `emit_iter_inputs`,
`emit_compositor_tree`, `eevee_engine_id`) plus `build_server_instructions`.
No bpy dependency, fully offline-testable.

**0.2 — Version plumbing:** `get_blender_version` closure added to
`server.py` and threaded through `register()` on `blender.py`, `verify.py`,
and `pipeline.py`. Each module exposes `_ver()` for tool code-gen.

**0.3 — Dynamic MCP instructions:** Server instructions now built at startup
from the detected Blender version. Includes version string, API mode
(5.x bracket access / 4.x id-property), compositor tree accessor, and
EEVEE engine ID. Injected into agent context on every turn by MCP protocol.

**0.4 — Migrated all inline version branches:**
- `set_parameter` — replaced broken `getattr` + `.default_value` with
  `emit_write_input()`. **Fixes feedback E (005 misfire).**
- `sweep` — same replacement. **Fixes feedback E (005 misfire).**
- `get_modifier_inputs` — replaced broken `dir()` + `getattr()` +
  `.default_value` with `emit_iter_inputs()`. Now surfaces `attribute_name`.
  **Fixes feedback D (005 misfire).**
- All compositor tree lookups in `blender.py`, `verify.py`, `pipeline.py`
  migrated to `emit_compositor_tree()`.
- EEVEE engine ID docstring updated.

**0.5 — Tests:** 27 new tests in `tests/test_version_routing.py` covering
compat helpers, dynamic instructions, and version-parameterized tool code-gen
(both 4.x and 5.x paths). All 269 existing tests updated and passing.

**Key result:** Zero `bpy.app.version` references remain in MCP tool code.
All version routing is host-side at code-gen time. Generated code is clean,
branchless Python native to the target Blender version.

**Side effect:** The 005 API misfires for `get_modifier_inputs`,
`set_parameter`, and `sweep` are already fixed. Stages 2.2 and 4 only need
verification and extension, not re-implementation of the core fix.
