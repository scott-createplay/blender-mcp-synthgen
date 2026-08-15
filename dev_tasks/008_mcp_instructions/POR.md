# POR — MCP server instructions: backend + viewpoint

**Status:** Stage 1 complete (viewpoint text approved). Ready for
implementation (Stages 2–5).

## Problem

When Claude Code (or any MCP client) connects to synthgen, every agent —
main session and subagents — receives the server's `instructions` string.
Today that string is two sentences:

```
Connected to Blender 5.2.0. API mode: 5.x — ...

Grounded Blender tools for procedural 3D synthetic data.
Schema-validated node/socket identifiers, scene-graph introspection,
and procedural authoring — never hallucinates Blender API names.
```

This tells agents *what the tools are* but not *how to think with them*.
The procedural-first philosophy, build-verify loop, derive-don't-set
discipline, and domain knowledge live in `skill/SKILL.md` and
`knowledge/` — files no agent reads unless explicitly told to.

Result: subagents approach Blender imperatively (reach for `bpy.ops`,
hand-set values, skip schema grounding) instead of thinking procedurally.
The instructions field is the one place every connecting agent reads
automatically — it's the right delivery mechanism.

## Goal

Two-layer instruction system:

1. **Backend** (hardcoded, ships with addon) — mechanical correctness
   rules that never change. Tool grounding, schema-first discipline,
   API version notes. Not a philosophy — just "how to use these tools
   without breaking things."

2. **Viewpoint** (user-settable in addon preferences) — the agent's
   default posture. Sets how the agent *thinks about* Blender, not
   what it's allowed to do. Ships with a procedural-first default
   for synthetic data, but the user owns it and can change or clear it.

Final `instructions` string = `api_notes + backend + viewpoint`.

**What we deliberately leave out:** Project-specific context (what
you're building, current goals, domain details). That belongs in the
conversation: CLAUDE.md, knowledge files, docs the user pastes in,
chat context. Baking project context into MCP instructions would
over-constrain agents and create rigidity where flexibility is needed.
The viewpoint sets the default posture, not a hard constraint — an
agent framed with "think procedurally" can still do an imperative edit
when the user asks.

## Design decisions (locked)

- **Two layers only.** Backend (hardcoded) + viewpoint (user-set).
  No project-context layer — that flows through conversation, docs,
  CLAUDE.md.
- **Instructions are server-side only.** No `.claude/` or client-side
  config involved. MCP `instructions` field is the delivery mechanism.
- **Viewpoint is a default posture, not a constraint.** It sets what
  agents reach for first, not what they're allowed to do.
- **Default viewpoint ships with the addon** as the StringProperty
  default. Users who clear it get backend-only instructions. Users
  who edit it own their framing.
- **Viewpoint references knowledge files by path** rather than
  inlining their content. Keeps the viewpoint small (~1100 bytes);
  agents read the relevant knowledge file on demand when building.
- **Server restart required** for viewpoint changes. Acceptable for
  a preference that changes rarely.

## Approved texts

### Backend instructions (hardcoded constant)

```
## Tool rules

- Schema first. Never guess node or socket identifiers. Call
  `schema_find` / `schema_show` before creating or wiring nodes.
  Socket label ≠ identifier.
- Structured tools first. Use `add_node`, `link_sockets`,
  `build_graph`, `set_socket_default` over `execute_python` when a
  structured tool exists. `execute_python` is the escape hatch.
- Verify after mutation. Mutations invalidate the graph cache.
  After bulk changes, verify with `evaluate_object` or
  `graph_snapshot`. Read-only tools (`schema_*`, `graph_*`) are
  free — use them liberally.
```

### Default viewpoint (ships as StringProperty default)

```
You are not editing a scene. You are authoring a machine that
produces scenes. Every node graph, driver, and expression you
create is part of a system with inputs, controls, and outputs —
closer to a reusable Houdini HDA than a saved file.

First instinct: derive. Compute values from scene signals — position,
normal, curvature, proximity, noise — rather than assigning constants.
Derived values can be swept and randomized; hand-set values are dead
ends. If a property can't be varied from code, it's invisible to a
parameter sweep.

Blender's procedural surface is not just Geometry Nodes. Shader nodes
handle appearance. The compositor handles image-space passes and
labels. Drivers wire parametric relationships across the scene graph.
These connect through named attributes and render passes — one
interconnected machine, not separate tools.

Expose controls. Surface the parameters that matter and bury the
rest. The interface of your system is as important as its internals.

Verify across the parameter space. One seed, one frame, one camera
angle is never proof. Vary inputs and confirm the output stays
coherent under change.

Before building, read the relevant knowledge file:
- knowledge/procedural_paradigm.md — how to think procedurally
- knowledge/houdini_to_geonodes.md — Houdini SOPs → Geometry Nodes
- knowledge/attribute_bridge.md — GN ↔ shader cross-talk
- knowledge/cop_to_compositor.md — compositor passes and labels
- knowledge/scene_graph_contexts.md — cross-context edge model

When the user asks for direct scene manipulation — specific placement,
specific values — do exactly that. This posture is a default, not a
cage.
```

## Implementation plan

### Stage 2 — Backend instructions + refactored assembly (compat.py)

**File:** `src/synthgen/mcp/tools/compat.py` (lines 124–151)

**Current state:** `build_server_instructions(ver)` takes only a
version tuple and returns a single string combining API notes with
a one-liner description.

**Changes:**

1. Add `_BACKEND_INSTRUCTIONS` constant (the "Tool rules" text above)
   after line 121 (below the existing engine ID section).

2. Add `_DEFAULT_VIEWPOINT` constant (the approved viewpoint text
   above) after the backend constant. This constant is used as the
   default value for the addon preference — it lives here (not in
   `__init__.py`) so the text is in one place and testable offline.

3. Refactor `build_server_instructions()` signature:

   ```python
   def build_server_instructions(
       ver: tuple[int, ...],
       viewpoint: str = "",
   ) -> str:
   ```

4. Assembly logic:
   ```python
   parts = [
       f"Connected to Blender {ver_str}. {api_notes}",
       _BACKEND_INSTRUCTIONS.strip(),
   ]
   if viewpoint.strip():
       parts.append("## Viewpoint\n\n" + viewpoint.strip())
   return "\n\n".join(parts)
   ```

5. The existing two-line description ("Grounded Blender tools...")
   is removed — its content is superseded by the backend rules and
   viewpoint.

6. Export `DEFAULT_VIEWPOINT` (public name for `_DEFAULT_VIEWPOINT`)
   so `__init__.py` can import it for the property default.

### Stage 3 — Viewpoint preference in addon (__init__.py)

**File:** `addon/synthgen_mcp/__init__.py` (lines 88–119)

**Changes to `SynthgenMCPPreferences`:**

1. Import the default viewpoint text:
   ```python
   from synthgen.mcp.tools.compat import DEFAULT_VIEWPOINT
   ```
   This import must happen lazily (inside `register()` or in the
   class body after paths are set up) because `synthgen` is not on
   `sys.path` until `_setup_paths()` runs. **Safest approach:** use
   a string literal copy of the default in the property definition,
   OR defer the import and set the default in `register()`.

   **Recommended:** Since Blender property defaults must be string
   literals at class definition time, define the default inline in
   the StringProperty and keep `_DEFAULT_VIEWPOINT` in compat.py as
   the canonical source. Add a test that asserts they match.

2. Add `viewpoint` property after `log_level` (line 112):
   ```python
   viewpoint: bpy.props.StringProperty(
       name="Agent Viewpoint",
       description=(
           "Default posture for AI agents connecting via MCP. "
           "Sets how agents think about Blender — procedural-first, "
           "traditional modeling, or custom. Clear for no viewpoint. "
           "Changes take effect after server restart."
       ),
       default=<DEFAULT_VIEWPOINT_TEXT>,
       maxlen=2000,
   )
   ```

   Note: `bpy.props.StringProperty` does not have a `subtype` for
   multi-line editing. For a multi-line UI, use `layout.prop()` with
   a text datablock or multiple rows. **Simplest approach:** use a
   single `layout.prop(self, "viewpoint")` — it renders as a text
   field. Users with long viewpoints can edit the string. If multi-line
   UX is important, that's a follow-up enhancement, not a blocker.

3. Update `draw()` method (line 114) to show the viewpoint field:
   ```python
   def draw(self, context):
       layout = self.layout
       layout.prop(self, "port")
       layout.prop(self, "auto_start")
       layout.prop(self, "log_level")
       layout.separator()
       layout.label(text="Agent Viewpoint (restart server to apply):")
       layout.prop(self, "viewpoint", text="")
   ```

### Stage 4 — Wire viewpoint through server startup

The viewpoint must be read from addon prefs on the **main thread**
(where `bpy.context` is safe) and passed as data to the server
thread. The server thread (`_build_and_run`) cannot safely access
`bpy.context.preferences`.

**File:** `addon/synthgen_mcp/__init__.py` — `_deferred_start()`
(line 144)

**Current:**
```python
def _deferred_start():
    prefs = bpy.context.preferences.addons.get(__package__)
    port = prefs.preferences.port if prefs else 8400
    try:
        srv.start(port, _addon_dir)
```

**Change to:**
```python
def _deferred_start():
    prefs = bpy.context.preferences.addons.get(__package__)
    port = prefs.preferences.port if prefs else 8400
    viewpoint = prefs.preferences.viewpoint if prefs else ""
    try:
        srv.start(port, _addon_dir, viewpoint=viewpoint)
```

**File:** `addon/synthgen_mcp/server.py` — `start()` (line 108)

**Current:**
```python
def start(port: int, addon_dir: str) -> None:
```

**Change to:**
```python
def start(port: int, addon_dir: str, viewpoint: str = "") -> None:
```

Pass `viewpoint` through to `_build_and_run()`:

```python
_server_thread = threading.Thread(
    target=_build_and_run,
    args=(port, addon_dir, viewpoint),
    ...
)
```

**File:** `addon/synthgen_mcp/server.py` — `_build_and_run()` (line 26)

**Current:**
```python
def _build_and_run(port: int, addon_dir: str) -> None:
    ...
    instructions=build_server_instructions(version),
```

**Change to:**
```python
def _build_and_run(port: int, addon_dir: str, viewpoint: str = "") -> None:
    ...
    instructions=build_server_instructions(version, viewpoint),
```

### Stage 5 — Deploy + validate

1. `pytest` — confirm all existing tests pass (instructions don't
   touch tool logic).

2. `python tools/deploy_addon.py` — deploy the updated addon.

3. Open Blender → Edit → Preferences → Add-ons → Synthgen MCP:
   - Verify "Agent Viewpoint" field appears with default text populated
   - Verify the restart note label is visible

4. Connect Claude Code → check the `<system-reminder>` MCP server
   instructions section. It should show:
   - API version notes (existing)
   - `## Tool rules` section (new backend)
   - `## Viewpoint` section (new, with default viewpoint text)

5. Spawn a subagent → verify it also receives the full instructions
   (not just the main session).

6. In Blender preferences, edit the viewpoint to a custom string →
   restart server (disable/enable addon or restart Blender) → verify
   the custom viewpoint appears in Claude Code's system context.

7. Clear the viewpoint field → restart → verify only API notes +
   Tool rules appear (no `## Viewpoint` section).

8. `python tools/validate_addon.py` — confirm health + tool calls
   still work.

## Key files

| File | Lines | Change |
|------|-------|--------|
| `src/synthgen/mcp/tools/compat.py` | 124–151 | Add `_BACKEND_INSTRUCTIONS`, `_DEFAULT_VIEWPOINT`, refactor `build_server_instructions()` |
| `addon/synthgen_mcp/__init__.py` | 88–119, 144–155 | Add `viewpoint` StringProperty to prefs, update `draw()`, pass viewpoint in `_deferred_start()` |
| `addon/synthgen_mcp/server.py` | 26, 50, 108, 128–130 | Add `viewpoint` param to `_build_and_run()` and `start()`, pass to `build_server_instructions()` |

## Tests

The existing 315 tests don't touch server instructions or addon
preferences. They will remain green.

**New test (optional but recommended):** Add a test in the offline
test suite that:
- Calls `build_server_instructions((5, 2, 0))` with no viewpoint →
  asserts output contains "Tool rules" but no "Viewpoint" section
- Calls `build_server_instructions((5, 2, 0), viewpoint="custom")`
  → asserts output contains both "Tool rules" and "## Viewpoint"
  sections with "custom" in the viewpoint
- Calls with empty/whitespace viewpoint → asserts no "Viewpoint"
  section

## Risk assessment

**Very low risk.** This changes the `instructions` string passed to
`FastMCP()` and adds one addon preference property. No tool logic,
no transport, no schema code is affected.

The main risk is the Blender `StringProperty` maxlen of 2000 chars —
the default viewpoint is ~1100 bytes, well within budget. If users
need longer viewpoints, `maxlen` can be increased later.

Thread safety: the viewpoint is read on the main thread in
`_deferred_start()` and passed as an immutable string to the server
thread. No shared mutable state.
