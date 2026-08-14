# POR — Mutation hardening (field-feedback fixes)

## Problem

The first real agent session — building a 14-node GN seed-scatter network in Blender
5.2 — took ~100 tool calls, ended in a hung Blender, and produced zero output until
the final diagnosis. The introspection layer (schema, graph) was correct every time.
Every failure lived in the mutation layer:

- **Silent version incompatibility.** `set_parameter` is 100% broken on Blender 5.x
  but emits a raw bpy traceback instead of saying so.
- **Partial state on failure.** `expose_parameter` creates the socket *before*
  validating defaults, leaving orphans with no structured way to clean them up.
- **Missing CRUD tools.** The agent used `execute_python` 5 times because no
  structured tool existed (create node group, remove object/collection/parameter,
  read modifier inputs).
- **68 mutation calls for one graph.** Every node, link, and parameter is a separate
  round-trip. Batch submission would collapse this to ~1–4 calls.
- **Half-built state is invisible.** Graph introspection can't distinguish "empty"
  from "modifier has `node_group = None`" — the exact moment when visibility matters.
- **Errors are empty strings.** A blocked main thread produces
  `"Error executing tool execute_python:"` with nothing after the colon.

Source: `SYNTHGEN_MCP_FEEDBACK.md` from the agent that ran the session.

## Goal

Harden the mutation layer so a realistic procedural authoring session
(14+ nodes, 30+ links, exposed parameters, sweep) completes reliably in
≤10 tool calls with clear diagnostics on every failure.

## Decisions locked

- **No new transport.** All changes are tool-level; the SSE + main-thread executor
  architecture is correct and stays.
- **Offline-testable first.** Every new tool gets a pytest that runs without Blender
  (code-generation check or mock transport). bpy integration tests are optional/manual.
- **Backwards compatible.** Existing tool signatures don't break. New parameters are
  optional; new tools are additive.
- **Sidecar saves only.** Auto-save never overwrites the user's file.

## Stages

### Stage 1 — Robustness: errors, version detection, partial-state

Fix the silent failures that cost the most debugging time.

#### 1.1 Transport timeout with actionable message

The transport's `execute_python` blocks forever when the main thread hangs. Add a
configurable timeout (default 30s). On timeout, return:
`"Blender did not respond within 30s — the main thread may be blocked; the session
likely needs a restart."`

**Files:** `src/synthgen/mcp/transport.py` (or `addon/synthgen_mcp/server.py` —
wherever `execute_python` awaits the Future)

**Validation:**
- [ ] Mock test: Future that never resolves → timeout error within tolerance
- [ ] Error message includes the timeout duration and restart guidance

#### 1.2 Blender version detection at server start

Detect the Blender major.minor version on first transport connection. Store it as
`transport.blender_version` (tuple). Tools that behave differently per version can
branch on it.

**Files:** `src/synthgen/mcp/transport.py`, startup probe code

**Validation:**
- [ ] After server start, `transport.blender_version` is populated (e.g. `(5, 2)`)
- [ ] Schema tools still work without version info (graceful fallback)

#### 1.3 Fix `set_parameter` for Blender 5.x

The current code does `mod[socket_identifier] = value`, which is the 4.x id-property
API. In 5.x, GN modifier inputs are on `mod.properties.inputs` (a
`GeometryNodesModifierInterface`) where socket identifiers are attribute names.

Branch on `transport.blender_version`: if ≥ 5.0, use the new API path. If version is
unknown, try the 5.x path first and fall back to 4.x with a warning.

**Files:** `src/synthgen/mcp/tools/pipeline.py` (`set_parameter`)

**Validation:**
- [ ] Code-gen test: generates correct code for version=(5,2) and version=(4,4)
- [ ] Error message on failure includes the Blender version and API path used

#### 1.4 Fix `expose_parameter` — validate before mutate, coerce int

Current code creates the socket, *then* sets `default_value`. If the assignment
fails (e.g. float for an int socket), the socket is orphaned.

Fix:
1. Coerce `default_value` to `int()` when `socket_type == "NodeSocketInt"`.
2. Move the default/min/max assignments into a `try`/`except` block in the generated
   code; on failure, remove the socket and re-raise.

**Files:** `src/synthgen/mcp/tools/blender.py` (`expose_parameter`)

**Validation:**
- [ ] Code-gen test: float default for int socket → code contains `int(...)` coercion
- [ ] Code-gen test: generated code has rollback (`interface.remove(sock)`) in except
- [ ] No orphan socket on failure path

#### 1.5 Make `reason` required on `execute_python`

The `reason` parameter currently defaults to `""`. Change it to have no default so
the caller must supply one. This preserves the audit trail.

**Files:** `src/synthgen/mcp/tools/blender.py` (`execute_python`)

**Validation:**
- [ ] MCP introspection shows `reason` as required (no default)
- [ ] Existing tests still pass (they should already supply a reason)

---

### Stage 2 — Missing CRUD tools

Close the holes in the procedural fence that force `execute_python` escapes.

#### 2.1 `create_node_group`

Create a new `GeometryNodeTree` (or `ShaderNodeTree` / `CompositorNodeTree`) and
return its name. This is the gap that `add_gn_modifier` falls into — it creates a
modifier but can leave `node_group = None` if no tree_name is given and the auto-
creation path fails silently.

**Files:** `src/synthgen/mcp/tools/blender.py`

**Validation:**
- [ ] Code-gen test: creates tree, returns `{"name": ..., "type": ...}`
- [ ] Supports "gn", "shader", "compositor" tree types

#### 2.2 `remove_object`

Remove an object from the scene by name. Unlinks from all collections first.

**Files:** `src/synthgen/mcp/tools/blender.py`

**Validation:**
- [ ] Code-gen test: generated code calls `bpy.data.objects.remove()`
- [ ] Error if object not found (with list of available objects)

#### 2.3 `remove_collection`

Remove a collection by name. Optionally removes child objects.

**Files:** `src/synthgen/mcp/tools/blender.py`

**Validation:**
- [ ] Code-gen test: generated code calls `bpy.data.collections.remove()`
- [ ] `remove_children` parameter controls child object cleanup

#### 2.4 `remove_parameter`

Remove a socket from a GN group interface by identifier. The inverse of
`expose_parameter`. Returns the updated full interface list.

**Files:** `src/synthgen/mcp/tools/blender.py`

**Validation:**
- [ ] Code-gen test: removes by identifier, not by name (names aren't unique)
- [ ] Returns full `items_tree` dump after removal

#### 2.5 `get_modifier_inputs`

Read-only tool. Return all input sockets of a GN modifier — identifier, name, type,
current value, default, min, max. Branches on Blender version (4.x id-props vs 5.x
`properties.inputs`).

**Files:** `src/synthgen/mcp/tools/blender.py` (or `verify.py` — it's read-only)

**Validation:**
- [ ] Code-gen test for version=(5,2) uses `mod.properties.inputs`
- [ ] Code-gen test for version=(4,4) uses `mod[identifier]`
- [ ] Returns list of `{identifier, name, type, value}` dicts

---

### Stage 3 — Richer mutation responses + ordering fixes

Make mutations self-describing so the agent's model doesn't drift.

#### 3.1 `expose_parameter` returns full interface

After creating (or failing to create) a socket, return the *entire* current
`interface.items_tree` — not just the new socket. This keeps the agent's view in sync
even when identifier allocation has gaps from prior failures.

**Files:** `src/synthgen/mcp/tools/blender.py` (`expose_parameter`)

**Validation:**
- [ ] Code-gen test: output includes `"interface": [...]` with all sockets
- [ ] Each entry has `identifier`, `name`, `socket_type`, `in_out`

#### 3.2 `add_gn_modifier` always creates + assigns a tree

When `tree_name` is not provided, `add_gn_modifier` should create a new
`GeometryNodeTree`, assign it to the modifier, and return the tree name. The current
code leaves `node_group = None` in some paths.

Also add Group Input / Group Output nodes to the new tree (Blender doesn't always do
this automatically).

**Files:** `src/synthgen/mcp/tools/blender.py` (`add_gn_modifier`)

**Validation:**
- [ ] Code-gen test: no-tree_name path creates tree + assigns it
- [ ] Return value includes `"tree_name": ...` always
- [ ] Generated code adds Group Input/Output nodes

#### 3.3 `expose_parameter` refreshes bound modifiers

After adding/removing an interface socket, find all modifiers in the scene whose
`node_group` points to this tree and trigger a refresh (re-read the interface). This
prevents the ordering trap where a modifier bound before the interface exists has all
inputs read 0.

**Files:** `src/synthgen/mcp/tools/blender.py` (`expose_parameter`)

**Validation:**
- [ ] Code-gen test: generated code iterates objects/modifiers and refreshes matches
- [ ] Return value includes count of refreshed modifiers

#### 3.4 Return ungrounded cost in mutation results

Any tool that calls `_run(code, mutates=True)` should include in its result:
`"ungrounded": "graph will re-resolve on next query"`. This is currently only in
tool descriptions, which the agent reads once and forgets.

**Files:** `src/synthgen/mcp/tools/blender.py` (`_run` helper or each tool)

**Validation:**
- [ ] At least 3 mutation tool outputs include the `ungrounded` field
- [ ] Read-only tools do NOT include it

---

### Stage 4 — Observability

New introspection + auto-save.

#### 4.1 `evaluate_object` tool

New read-only tool. Evaluates the depsgraph for an object and returns:
```json
{
  "name": "city_seeds",
  "type": "MESH",
  "verts": 4,
  "edges": 4,
  "faces": 1,
  "points": 0,
  "attributes": ["position", "normal", ...],
  "modifier_count": 1,
  "modifier_warnings": ["Input 'Ground Size X' has no value"],
  "modifiers": [
    {"name": "seed_scatter", "type": "NODES", "node_group": "scatter_net"}
  ]
}
```

Uses `bpy.context.evaluated_depsgraph_get()` and `NodesModifier.node_warnings`.

**Files:** `src/synthgen/mcp/tools/verify.py`

**Validation:**
- [ ] Code-gen test: generates depsgraph evaluation code
- [ ] Output schema includes verts/faces/attributes/modifier_warnings
- [ ] Read-only — does not call `_run(..., mutates=True)`

#### 4.2 Graph tools surface unresolved modifier state

When `graph_nodes` encounters a modifier with `node_group = None`, emit an entry like
`MOD:seed_scatter → node_group: None` instead of silently omitting it. Similarly,
`graph_neighbors` on such a modifier should return a diagnostic edge or annotation
rather than `[]`.

**Files:** `src/synthgen/scenegraph/backend_bpy.py` (or the graph tool layer)

**Validation:**
- [ ] A modifier with `node_group = None` appears in `graph_nodes` output
- [ ] The entry clearly indicates the unresolved state

#### 4.3 Auto-save sidecar after successful mutations

After each successful mutating call, save to `<user_file>.autosave.blend` (or a temp
path if the scene has no file). Skip for read-only calls. Include a size/time guard
so large scenes don't block (log a warning instead of saving if the last save took
>2s).

**Files:** `src/synthgen/mcp/tools/blender.py` (`_run` helper), transport layer

**Validation:**
- [ ] Sidecar file created after mutation, never overwrites original
- [ ] Read-only calls do not trigger save
- [ ] Size guard: skips with warning if last save exceeded threshold

---

### Stage 5 — Batch operations

The single biggest call-count reduction.

#### 5.1 `build_graph` compound tool

Accept a complete graph specification in one call:

```json
{
  "tree_name": "scatter_net",
  "tree_type": "gn",
  "nodes": [
    {"type": "GeometryNodeDistributePointsOnFaces", "name": "scatter"},
    {"type": "GeometryNodeInputMeshFaceArea", "name": "face_area"}
  ],
  "links": [
    {"from_node": "face_area", "from_socket": "Area",
     "to_node": "scatter", "to_socket": "Density Factor"}
  ],
  "parameters": [
    {"socket_type": "NodeSocketFloat", "name": "Density", "default": 10.0,
     "min": 0.0, "max": 100.0}
  ],
  "defaults": [
    {"node": "scatter", "socket": "Distance Min", "value": 2.0}
  ]
}
```

Generates a single Python script that:
1. Validates all node types against the grounding schema (fail-fast, nothing created)
2. Creates all nodes
3. Creates all links
4. Exposes all parameters (with int coercion)
5. Sets all defaults
6. Returns the full tree state (nodes, links, interface)

On any failure, rolls back the entire tree (delete it).

If `build_graph` is too large for a first pass, implement plural variants instead:
`add_nodes`, `link_many`, `expose_parameters`, `set_defaults` — each taking a list.

**Files:** `src/synthgen/mcp/tools/blender.py`

**Validation:**
- [ ] Code-gen test: 14 nodes + 31 links + 14 params → single generated script
- [ ] All node types validated before any mutation (fail-fast)
- [ ] Rollback on partial failure (tree deleted)
- [ ] Return value includes full tree state
- [ ] Call count for the feedback session's graph: ≤ 5 (down from 68)

---

## Definition of done

- [ ] **Stage 1:** All 5 robustness fixes landed; `set_parameter` works on 5.x;
  `expose_parameter` never orphans sockets; timeouts produce actionable messages
- [ ] **Stage 2:** All 5 CRUD tools exist; agent can build a full GN network without
  `execute_python` for structural operations
- [ ] **Stage 3:** Mutations return full state; `add_gn_modifier` never leaves
  `node_group = None`; modifier refresh on interface changes
- [ ] **Stage 4:** `evaluate_object` exists; graph sees unresolved state; auto-save
  works
- [ ] **Stage 5:** `build_graph` (or plural variants) reduces a 14-node graph build
  from 68 calls to ≤ 5
- [ ] All offline tests pass (`pytest`)
- [ ] No regressions in existing 33 tools

## Risks

| Risk | Mitigation |
|---|---|
| `build_graph` rollback complexity | Start with plural variants; promote to `build_graph` once the individual tools are solid |
| Auto-save blocking on large scenes | Size/time guard with skip + warning |
| Blender 5.x `properties.inputs` API may vary by 5.x minor version | Test against 5.2 LTS specifically; document any 5.0/5.1 gaps |
| Modifier refresh after `expose_parameter` could be expensive | Only refresh modifiers bound to the same tree, not all modifiers in the scene |

## Key context

- Feedback source: `blender_camera_distribution_pkg/tools/SYNTHGEN_MCP_FEEDBACK.md`
- Current tools: `src/synthgen/mcp/tools/{blender,graph,pipeline,schema,verify}.py`
- Transport: `addon/synthgen_mcp/server.py` (SSE), `src/synthgen/mcp/transport.py`
- Blender 5.x API notes: `blender_camera_distribution_pkg/tools/BLENDER_5x_NOTES.md`
