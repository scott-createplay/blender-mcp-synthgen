# SynthGen UI Toolbox -- Plan of Record

## Problem

Two capabilities exist only in the agent/script layer with no UI equivalent:

1. **Asset export.** Building SynthGen assets via Python build scripts
   (`scripts/build_*.py`) is slow, brittle, and painful. The user can author
   a node group in Blender's UI in minutes, but there's no way to
   deterministically export it as a registered SynthGen asset. The user must
   either hand off to the script pipeline or manually replicate the metadata
   that `mark_assets.py` handles. The SDF Ops asset took multiple sessions
   and 6 discovered Blender 5.2 API bugs to build via script; the user's
   manual prototype worked on the first try.

2. **Auto layout.** The MCP server has a topological auto-layout algorithm
   (`_layout_code` in `blender.py:78-122`) that runs automatically on every
   `add_node`, `link_sockets`, and `build_graph` call. It arranges nodes
   right-to-left with sinks rightmost and sources leftmost. The user has no
   access to this -- they must manually arrange nodes or ask the agent to
   run `layout_node_tree` via MCP. This should be a button.

Both violate the shared collaboration plane principle: the agent has powers
the user doesn't. ([[shared-collaboration-plane]])

## Goal

- **One-click asset export.** Select a node group, pick a category, get a
  registered SynthGen asset in `assets/` with all metadata and a manifest stub.
- **One-click auto layout.** Button in the node editor that runs the same
  topological layout the agent uses. Works on any node tree (GN, shader,
  compositor).
- **Shared authoring plane.** Both capabilities accessible from UI and MCP.
  Same implementation, same output.

## Reference

- `src/synthgen/mcp/tools/blender.py:78-122` -- `_layout_code()` algorithm
- `scripts/mark_assets.py` -- current registration pipeline
- `addon/synthgen_mcp/operators.py` -- existing operators (create container,
  add/remove asset)
- `knowledge/asset_composition.md` -- asset author rules
- `assets/*.md` -- asset manifest format

## Architecture

### Auto Layout

The layout algorithm already exists as inline Python in `_layout_code()`.
To expose it:

1. **Extract** the algorithm into a standalone function in
   `src/synthgen/layout.py` that takes a `bpy.types.NodeTree` directly
   (no code-generation, no string templating).
2. **Blender operator** `SYNTHGEN_OT_auto_layout` calls that function on
   the active node tree.
3. **MCP tool** `layout_node_tree` calls the same function (replacing the
   current code-gen approach).
4. **`_layout_code()`** still exists for the inline-in-mutation case
   (`add_node`, `link_sockets`, `build_graph`) where a standalone call would
   be a wasted round-trip -- but it's generated FROM the canonical function,
   not a separate copy.

```
                   ┌─────────────────┐
                   │  layout.py      │  Canonical implementation
                   │  auto_layout()  │  Takes a bpy.types.NodeTree
                   └────────┬────────┘
                    ┌───────┼────────┐
                    ▼       ▼        ▼
              Operator   MCP tool   Inline codegen
              (UI btn)   (agent)    (add_node etc.)
```

Algorithm (current, preserved):
- Build forward/backward adjacency from links
- Find sinks (nodes with no forward edges = outputs)
- BFS backward to assign layer depth
- Place columns right-to-left, 300px apart
- Vertical spacing = `max(150, 30 * (inputs + outputs))`

### Save Asset

```
User builds node group in Blender UI
              │
              ▼
   ┌──────────────────────┐
   │  Tag as Asset         │  Sets synthgen_asset property
   │  (SynthGen > Asset    │  Auto-prefixes "SynthGen." if missing
   │   > Tag as Asset)     │  Also callable via MCP: tag_asset(tree_name)
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  Save Asset           │  Category dialog → export
   │  (SynthGen > Asset    │  Poll: must be tagged + is a group
   │   > Save Asset)       │  Also callable via MCP: save_asset(tree_name)
   └──────────┬───────────┘
              │
     ┌────────┼────────┐
     ▼        ▼        ▼
  Validate  Export   Catalog
     │     (isolate    │
     │      .blend)    │
     │        │        │
     └────────┼────────┘
              │
              ▼
   ┌──────────────────────┐
   │  assets/<name>.blend │  One node group per file
   │  assets/<name>.md    │  Manifest stub (if not already present)
   │  blender_assets.     │  Catalog entry added
   │    cats.txt          │
   └──────────────────────┘
```

#### Two-step workflow: Tag then Save

**Tag as Asset** is the lightweight gate. The user selects a node group in
the node editor, clicks Tag. This:
- Sets the `synthgen_asset` custom property on the node group
- Auto-prefixes `SynthGen.` on the group name if missing
- Is quick, reversible, no dialog needed

**Save Asset** is the deliberate export action. Poll requires the active
tree to be a tagged GeometryNodeTree group. Shows a category dropdown, then
exports to `assets/`. If the `.blend` already exists, overwrite it. If the
`.md` already exists, warn but do not clobber (user may have filled in
descriptions).

Future: visual indicator on tagged groups in the node editor (custom color
or icon overlay). Not a blocker for v1.

Future: Save dialog lists existing assets for update-in-place. The core
function supports this (accepts a target name), but v1 always saves based
on the group name.

#### Validation rules (on Save)

| Rule | Check | Action |
|------|-------|--------|
| Is tagged | `synthgen_asset` property present | Error (use Tag first) |
| Has interface | `len(inputs) > 0 or len(outputs) > 0` | Error |
| Named correctly | Starts with `SynthGen.` | Should already be prefixed by Tag |
| No Viewer nodes | `GeometryNodeViewer` present | Auto-strip from export |
| Defaults set | Sockets have sensible min/max | Warning |

#### Isolated .blend export

Save ONLY the target node group (and recursive sub-group dependencies) into
a clean `.blend`. No scene objects, cameras, or unrelated data. Approach:
run a headless Blender subprocess that opens the current file, appends the
node group, purges everything else, marks as asset, and saves.

#### Manifest generation

Auto-generate `assets/<slug>.md` with:
- Front matter (name, file, category, version, blender)
- Parameters table from interface sockets (identifier, type, default)
- Empty sections for the user to fill (description, attributes, composition)

The socket table is the high-value part -- eliminates manual identifier
transcription. Only generated if the `.md` does not already exist — never
clobbers a user-edited manifest.

## Decisions locked

- **One function, multiple callers.** Both layout and export have a single
  canonical implementation. Operator and MCP tool are thin wrappers.
- **Layout algorithm preserved as-is.** The topological layering works well.
  No redesign -- just extract and expose.
- **Selection-aware layout.** When nodes are selected, layout only those
  nodes. When nothing is selected, layout all nodes in the tree.
- **No auto-framing.** Layout and framing are separate concerns. The user
  hits `L` to lay out, then `Home`/`F` to frame if desired. The operator
  does not call `view_all` or `view_selected`.
- **One node group per .blend file.** Matches current convention.
- **Validation warns, doesn't block** (except "no interface"). The user
  knows what they built.
- **Viewer nodes auto-stripped from export only.** Never from the working file.
- **MCP mirrors are mandatory.** Every UI button has an MCP tool equivalent.

## Stages

### Stage 1: Extract layout into standalone module

**Goal:** `synthgen.layout.auto_layout(tree)` works as a direct `bpy` call.

1. Create `src/synthgen/layout.py`:
   ```python
   def auto_layout(tree, nodes=None, x_spacing=300, y_min=150, y_per_socket=30):
       """Topological auto-layout for a Blender node tree.

       If *nodes* is provided, layout only those nodes (links between
       them still used for ordering). If None, layout all nodes in the
       tree.

       Sinks (Group Output, nodes with no forward edges) are placed
       rightmost. Sources are placed leftmost. Vertical spacing is
       estimated from socket count.
       """
   ```

2. Port the algorithm from `_layout_code()` -- same logic, but operating
   on `tree.nodes` and `tree.links` directly instead of generating Python
   source strings. When `nodes` is a subset, only consider links where
   both endpoints are in the subset.

3. Update `_layout_code()` in `blender.py` to generate code that calls
   `from synthgen.layout import auto_layout; auto_layout(tree)` -- OR keep
   the inline codegen for the mutation-path performance but ensure both
   implementations are tested identically.

4. Update `layout_node_tree` MCP tool to use the direct function call.

| File | Action |
|------|--------|
| `src/synthgen/layout.py` | Create |
| `src/synthgen/mcp/tools/blender.py` | Modify -- update layout_node_tree |
| `tests/test_layout.py` | Create -- offline tests |

**Verify:**
- [ ] `auto_layout(tree)` produces identical node positions to current `_layout_code()`
- [ ] `layout_node_tree` MCP tool works with the new implementation
- [ ] Inline codegen in `add_node` / `link_sockets` still works
- [ ] Offline tests pass (mock node tree)

### Stage 2: Blender operators + UI wiring

**Goal:** Two operators exposed via header menu, context menu, and keymap.

#### UI placement

```
Node Editor header:  View | Select | Node | SynthGen
                                             ├─ Asset
                                             │   ├─ Tag as Asset
                                             │   └─ Save Asset...
                                             └─ Layout
                                                 └─ Auto Layout    (L)

Right-click context menu:
    ├─ ...existing items...
    ├─ Auto Layout
    ├─ Tag as Asset             (GN group trees only)
    └─ Save Asset...            (tagged GN groups only)
```

- **Top-level "SynthGen" menu** in the Node Editor header bar, always
  visible. Individual items grayed out by poll when context doesn't apply.
- **Right-click context menu** entries for quick access.
- **Keymap: `L`** in the Node Editor keymap for Auto Layout (Houdini parity).

#### Auto Layout operator

```python
class SYNTHGEN_OT_auto_layout(bpy.types.Operator):
    bl_idname = "synthgen.auto_layout"
    bl_label = "Auto Layout"
    bl_description = "Arrange nodes using topological layering"
    bl_options = {'REGISTER', 'UNDO'}
```

- **Poll:** Active space is `NODE_EDITOR` and a node tree is being edited.
- **Execute:**
  1. `selected = [n for n in tree.nodes if n.select]`
  2. If `selected`: layout only those nodes.
  3. If empty: layout all nodes in the tree.
  4. No framing — layout only.

#### Tag as Asset operator

```python
class SYNTHGEN_OT_tag_asset(bpy.types.Operator):
    bl_idname = "synthgen.tag_asset"
    bl_label = "Tag as Asset"
    bl_description = "Mark the active node group as a SynthGen asset"
    bl_options = {'REGISTER', 'UNDO'}
```

- **Poll:** Active space is `NODE_EDITOR`, editing a `GeometryNodeTree`,
  and the edit_tree is a node group (not the top-level modifier tree).
- **Execute:**
  1. Set `tree["synthgen_asset"] = True`
  2. If name doesn't start with `SynthGen.`, rename to `SynthGen.<name>`
  3. Report success

#### Save Asset operator

```python
class SYNTHGEN_OT_save_asset(bpy.types.Operator):
    bl_idname = "synthgen.save_asset"
    bl_label = "Save Asset"
    bl_description = "Export the tagged node group as a SynthGen asset"
    bl_options = {'REGISTER', 'UNDO'}

    category: bpy.props.EnumProperty(
        name="Category",
        items=[
            ('Distribution', 'Distribution', ''),
            ('Instancing', 'Instancing', ''),
            ('Camera', 'Camera', ''),
            ('Deformation', 'Deformation', ''),
            ('Container', 'Container', ''),
            ('Utility', 'Utility', ''),
        ]
    )
```

- **Poll:** Active space is `NODE_EDITOR`, editing a `GeometryNodeTree`,
  the edit_tree is a node group, AND `tree.get("synthgen_asset")` is truthy.
- **Invoke:** Dialog with category dropdown.
- **Execute:**
  1. Auto-save current file (so subprocess can read it)
  2. Validate the node group
  3. Run headless subprocess to produce isolated `.blend`
  4. Append catalog entry (idempotent)
  5. Generate manifest `.md` stub (skip if `.md` already exists)
  6. Refresh Asset Browser
  7. Report success

| File | Action |
|------|--------|
| `addon/synthgen_mcp/operators.py` | Modify -- add both operators |
| `addon/synthgen_mcp/menus.py` | Create -- SynthGen menu + context menu append |
| `addon/synthgen_mcp/__init__.py` | Modify -- register operators, menus, keymap |
| `src/synthgen/assets.py` | Create -- validate/export/manifest functions |
| `scripts/_export_asset_worker.py` | Create -- headless export subprocess |

**Verify:**
- [ ] "SynthGen" menu appears in Node Editor header bar
- [ ] Auto Layout appears in header menu, right-click menu, and responds to `L`
- [ ] Auto Layout: selected nodes → lays out only those; no selection → all nodes
- [ ] Auto Layout works on GN, shader, and compositor trees
- [ ] Tag as Asset: sets property + auto-prefixes name
- [ ] Tag as Asset: grayed out on non-group trees and non-GN trees
- [ ] Save Asset: grayed out when group is not tagged
- [ ] Save Asset: shows category dialog
- [ ] Exported asset appears in Asset Browser
- [ ] No duplicates after re-export
- [ ] Viewer nodes stripped from export, preserved in working file
- [ ] Generated `.md` has correct socket table
- [ ] `.md` not clobbered on re-export

### Stage 3: MCP tool mirrors

**Goal:** Both capabilities available via MCP.

1. `layout_node_tree` -- already exists, just confirm it uses the shared
   implementation from Stage 1.

2. Add `tag_asset` tool:
   ```python
   @server.tool("tag_asset")
   async def tag_asset(tree_name: str) -> dict:
       """Mark a node group as a SynthGen asset.
       Sets synthgen_asset property and auto-prefixes name.
       Returns {tree_name, tagged}."""
   ```

3. Add `save_asset` tool:
   ```python
   @server.tool("save_asset")
   async def save_asset(tree_name: str, category: str = "Utility",
                        version: str = "0.1") -> dict:
       """Export a tagged node group as a registered SynthGen asset.
       Returns {blend_path, manifest_path, catalog_id}."""
   ```

| File | Action |
|------|--------|
| `addon/synthgen_mcp/server.py` | Modify -- add tag_asset and save_asset tools |

**Verify:**
- [ ] Agent can tag a node group via MCP, then `save_asset` in one flow
- [ ] Output identical to UI operator
- [ ] Round-trip: save via MCP → import_asset → identical node group

## Risks

| Risk | Mitigation |
|------|------------|
| Headless subprocess can't access unsaved changes | Operator auto-saves first; MCP calls `save_checkpoint` |
| Node group has sub-group dependencies | Append-based export follows dependencies naturally |
| Catalog UUID collision | `uuid5(SYNTHGEN_NS, name)` → deterministic, collision-free |
| User re-exports same asset | Overwrite `.blend`, update catalog idempotently, warn if `.md` exists |
| Layout on huge trees is slow | Current algorithm is O(V+E), fast enough for any realistic tree |
| `auto_layout` import not available in codegen path | Keep inline codegen as fallback; test both paths |

## Open questions

- [ ] Should Auto Layout be registered as a keymap shortcut (e.g., Ctrl+L in
      node editor)?
- [ ] Should Save Asset support batch export (all `SynthGen.*` groups)?
- [ ] Should `mark_assets.py` be refactored to use `synthgen.assets.export()`,
      or kept as a separate legacy path?
- [ ] Should the manifest auto-generate the internal graph diagram (ASCII art),
      or leave that blank?

## Definition of done

### Stage 1
- [ ] `synthgen.layout.auto_layout()` exists and is tested offline
- [ ] MCP `layout_node_tree` uses the shared implementation
- [ ] Inline codegen still works for mutation tools

### Stage 2
- [ ] Auto Layout operator in Node Editor (header menu + right-click + `L`)
- [ ] Tag as Asset operator (sets property, auto-prefixes name)
- [ ] Save Asset operator with category dialog (poll requires tag)
- [ ] Exported asset appears in Asset Browser
- [ ] Generated `.md` has correct front matter and socket table
- [ ] `.md` not clobbered on re-export
- [ ] Viewer nodes handled correctly

### Stage 3
- [ ] `tag_asset` MCP tool works
- [ ] `save_asset` MCP tool works
- [ ] Full round-trip: tag → save → import → use
- [ ] Regression suite green
