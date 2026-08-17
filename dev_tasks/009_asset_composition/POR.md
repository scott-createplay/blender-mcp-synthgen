# Asset Composition & Container System — Plan of Record

## Problem

Assets exist as standalone node groups in `.blend` files, but there is no
managed way to:
- **Discover** them — the agent and user each maintain separate mental inventories
- **Compose** them — chaining Scatter → Instance requires manual wiring
- **Author together** — the user works in the node editor, the agent works through
  MCP tools, and neither can see what the other did without re-inspecting the scene

The prototype SynthGen container (built in the scatter session) proves the
composition model works, but it was hand-assembled in Python. No user can create
one from the Blender UI, and the agent has no tools to manage containers.

## Goal

A **shared authoring plane** where the user and the agent discover, compose, and
configure assets through the same underlying system:

- Assets registered in **Blender's native asset catalog** — not a parallel registry
- Containers (procedural contexts) managed by a Python module, exposed to both
  the addon UI and the MCP tools
- User creates a container from the N-panel, agent discovers it via MCP.
  Agent adds an asset via MCP, user sees it in the panel. Either side can author.

## Reference

- `knowledge/asset_composition.md` — container architecture
- `knowledge/well_known_attributes.md` — attribute contract (the data bus)
- `assets/scatter.md`, `assets/instance_on_points.md` — existing asset manifests
- Blender Asset System: `ID.asset_mark()`, `AssetMetaData`, `blender_assets.cats.txt`

## Architecture

### Two layers, one data model

```
┌─────────────────────────────────────────────────────────┐
│                  Blender's Data Model                   │
│                                                         │
│  bpy.data.node_groups     ← node groups (assets + containers)
│  blender_assets.cats.txt  ← catalog hierarchy           │
│  ID.asset_data            ← metadata, tags              │
│  node["synthgen_*"]       ← custom properties (containers)
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
    ┌──────┴──────┐           ┌───────┴───────┐
    │ Asset Layer │           │Container Layer│
    │             │           │               │
    │ Blender's   │           │ synthgen.     │
    │ asset system│           │ containers    │
    │ (catalog,   │           │ module        │
    │  tags,      │           │ (custom props,│
    │  metadata)  │           │  DAG wiring)  │
    └──────┬──────┘           └───────┬───────┘
           │                          │
    ┌──────┴──────────────────────────┴───────┐
    │          Shared Interface Layer          │
    │                                         │
    │  Addon UI (N-panel)    MCP Tools        │
    │  Asset Browser         Agent calls      │
    └─────────────────────────────────────────┘
```

**Asset layer:** Blender's native asset system. Each SynthGen node group is
`asset_mark()`'d with catalog IDs, tags, and descriptions. The addon registers
`assets/` as a Blender Asset Library. The Asset Browser shows them alongside
Blender's built-in assets. Users can drag-and-drop node groups from the Asset
Browser into any GN editor.

**Container layer:** Custom properties on node groups and nodes. Containers are
working state in the scene — NOT asset-marked. The `synthgen.containers` module
provides create/add/remove/list/find operations. Both the addon panel and MCP
tools call this module.

### Container tagging

```python
# On the container node group:
ng["synthgen_type"] = "container"
ng["synthgen_version"] = 1
ng.use_fake_user = True

# On each sub-group node inside the container:
node["synthgen_asset"] = "Scatter on Surface"  # asset identity
# Order is derived from tracing the geometry DAG — not stored.
```

### Asset tagging (Blender's system)

```python
ng.asset_mark()
ng.asset_data.description = "Distributes points across a mesh surface..."
ng.asset_data.author = "SynthGen"
ng.asset_data.catalog_id = "<uuid>"  # → "SynthGen/Distribution"
ng.asset_data.tags.new("scatter")
ng.asset_data.tags.new("distribution")
```

Catalog hierarchy (`blender_assets.cats.txt`):
```
VERSION 1

<uuid>:SynthGen:SynthGen
<uuid>:SynthGen/Container:SynthGen-Container
<uuid>:SynthGen/Distribution:SynthGen-Distribution
<uuid>:SynthGen/Instancing:SynthGen-Instancing
<uuid>:SynthGen/Deformation:SynthGen-Deformation
<uuid>:SynthGen/Shading:SynthGen-Shading
```

### Geometry DAG wiring

Assets inside a container are connected through the geometry stream. The chain
supports **DAG structure** (branching/merging), not just linear sequences.

```
Linear:     A ──→ B ──→ C

Branching:  A ──→ B ──→ D
            └──→ C ──→ ┘   (Join Geometry)

Parallel:   Input ──→ A ──→ Join ──→ Output
                  └──→ B ──→ ┘
```

Insert and remove are splice operations on the geometry links. The module
traces the DAG by following geometry socket connections from Group Input to
Group Output — wiring IS the order, no separate index.

## Decisions locked

- **Blender's asset catalog is the registry.** No parallel asset database. The
  addon registers its `assets/` directory as a Blender Asset Library. The agent
  queries the same catalog the user browses in the Asset Browser.
- **Container template is an asset; container instances are not.** A
  `SynthGen.Container` template lives in the catalog as a bootstrap preset
  — pre-wired input hook infrastructure (Object sockets → Object Info →
  Geometry routing, Collection inputs) so nobody has to hand-build the
  boilerplate. When instantiated (via menu or MCP), the instance is tagged
  as working state (`synthgen_type = "container"`) and NOT asset-marked.
  The template ensures consistency; the instance is mutable scene state.
- **Parameters stay at the sub-group level.** With N chained assets, bubbling
  all parameters to the container's modifier panel would cause collisions and
  clutter. Only global controls (Seed) go to the top. Users/agents configure
  assets by addressing the sub-group node.
- **Attributes are the bus.** Assets communicate through well-known named
  attributes on the geometry stream (`pscale`, `orient`, `N`, `id`, `density`).
  No explicit socket wiring between assets beyond the geometry stream.
- **Same asset type can appear multiple times.** Blender disambiguates with
  `.001` suffixes. The `synthgen_asset` tag records the asset type; the node
  name is the instance identity.
- **Cross-catalog discovery.** `add_asset()` searches ALL registered asset
  libraries — SynthGen's custom assets AND Blender's built-in GN library
  (Generate, Mesh, Instances, Utilities). A SynthGen asset is not special;
  it composes with any Blender node group asset.
- **SynthGen assets are namespaced.** Node group names use dot notation:
  `SynthGen.Scatter on Surface`, `SynthGen.Instance on Points`. This
  signals the asset participates in the well-known attribute contract
  (the shared attribute substrate) and eliminates name collisions with
  Blender's built-in assets. The catalog entry still uses the short name
  for browsing (`Scatter on Surface`). Verified safe: our addressing
  convention uses `:` and `/` as delimiters (not `.`), asset identity is
  tag-based (`synthgen_asset` property, not name-parsed), and Blender's
  `.001` dedup suffix coexists cleanly (`SynthGen.Scatter on Surface.001`).
  Guard: any future code stripping `.NNN` suffixes must check
  `parts[-1].isdigit()` before splitting.
- **The UI mirrors the agent's tools.** The addon's N-panel menu is a
  direct reflection of the MCP tools the agent has — same operations, same
  discovery, same topology. This is the shared collaboration plane: the user
  sees what the agent can do, and vice versa. Neither side has capabilities
  invisible to the other.
- **Post-creation discovery via scene topology.** Once assets are composed
  inside containers in the scene, both the agent and user discover them
  through the same navigable hierarchy:
  `SynthGen → in_scene → <object> → <container> → [assets in context]`.
  The agent accesses this as MCP resources (`synthgen://scene/containers/…`);
  the user sees it as a dynamic N-panel menu. The menu structure IS the
  resource tree — one data source, two views.
- **Containers are semantically labeled, not typed.** A container is a blank
  procedural context — the user decides what goes inside through conversation
  and exploration. Creating a container does not imply any particular pipeline.
- **DAG, not linear.** Branching and merging are supported. The geometry
  connections define the topology; tracing them discovers the structure.
- **Catalog creation is headless-safe.** `bpy.ops.asset.catalog_new` requires
  a live UI context. The module writes `blender_assets.cats.txt` directly for
  headless/MCP operation.
- **Check Blender's built-in library before building.** Blender ships a GN
  asset library (Generate, Mesh, Instances, Utilities). Step zero of any new
  asset: check if a built-in does it, fork if it's close, build only if not.
  See `knowledge/asset_composition.md` §5.
- **Containers are geometry-agnostic.** A container is a processing context
  with input hooks, not a wrapper around a specific mesh. It exposes Object
  reference inputs (hooks) that source geometry via Object Info nodes.
  Swap the input object → the whole pipeline recalculates. The container
  can live on an Empty (as a null/controller), on the target mesh, or on
  any object — it doesn't care. Multiple geometry inputs are supported
  (e.g., scatter surface + collision mesh). This mirrors Houdini's SOP
  context: the network has input connectors, not an inherent geometry.
- **Container creation is implicit infrastructure.** The agent creates a
  container as standard setup when beginning procedural work — like opening
  a SOP context before doing anything inside it. The container doesn't
  imply a specific pipeline; the user/agent decides what goes inside
  through conversation and exploration.

## Current prototype state

A hand-built SynthGen container exists in `assets/scatter.blend` from the
scatter development session. It demonstrates the composition model but was
assembled via `execute_python`, not through any managed tooling.

- **Container:** "SynthGen" node group on Ground object (4 nodes: Group Input,
  Scatter on Surface sub-group, Instance on Points sub-group, Group Output)
- **Scatter on Surface:** 46-node sub-group, density-aware relaxation, outputs
  point cloud with `pscale`, `orient`, `N`, `id` attributes
- **Instance on Points:** 11-node sub-group, reads `pscale`/`orient` from
  named attributes, Collection = ScatterObjects (Rock_A, Rock_B)
- **Verified:** 109 instances, pscale variation confirmed (0.5–2.0 range when
  Randomize Scale enabled), 54/55 Rock_A/Rock_B distribution (Pick Instance
  working), density gradient preserved

This prototype validates the architecture but has no tagging, no catalog
registration, and no managed create/add/remove workflow. Stage 0 starts by
registering the existing assets; Stage 1 replaces the hand-wiring with the
`synthgen.containers` module.

## Stages

### Stage 0: Asset catalog foundation

**Goal:** Existing assets (Scatter on Surface, Instance on Points) registered
in Blender's native asset catalog, discoverable through the Asset Browser.

1. Generate UUIDs for catalog entries.
2. Write `assets/blender_assets.cats.txt` with the SynthGen catalog hierarchy.
3. Write a script (`scripts/mark_assets.py`) that:
   - Opens each asset `.blend` file
   - Marks node groups as assets (`asset_mark()`)
   - Sets description, author, tags, catalog_id
   - Saves the `.blend`
4. Run the script on `scatter.blend` to mark Scatter on Surface and
   Instance on Points.
5. Document the asset registration process for future assets.

**Verify:**
- [ ] Open Blender, add `assets/` as an Asset Library in Preferences
- [ ] Asset Browser shows SynthGen catalog with both assets
- [ ] Assets have descriptions, tags, and correct catalog placement
- [ ] Drag-and-drop from Asset Browser into GN editor creates a Group node

### Stage 1: Container template + `synthgen.containers` module

**Goal:** Build the `SynthGen.Container` template asset (the bootstrap preset
with input hooks) and the Python module providing container lifecycle
operations. Importable with and without Blender (`import bpy` guarded).
Usable by both the addon and MCP tools.

**Container template (`SynthGen.Container`):**

A node group registered in the catalog under `SynthGen/Container`. Pre-wired
with:
- Object input socket ("Surface") → Object Info → Geometry
- Geometry Output
- Seed (Int) input
- Infrastructure for adding more Object/Collection inputs dynamically

The `create()` function instantiates this template, tags the instance, and
applies it as a GN modifier. The template is the asset; the instance is
working state. Built via a headless script (extending `mark_assets.py` or
a new `build_container_template.py`) and registered in `scatter.blend` or
a dedicated `container.blend`.

**Location:** `src/synthgen/containers.py`

**API:**

```python
def create(object_name: str, name: str = "SynthGen",
           inputs: dict[str, str] | None = None) -> dict:
    """Create an empty container on an object.
    Idempotent — returns existing container if one is already present.
    Tags node group with synthgen_type, applies as GN modifier.
    
    The container is geometry-agnostic — it exposes Object reference
    inputs (hooks) that source geometry via Object Info nodes. The
    host object need not be a mesh; an Empty works as a controller.
    
    `inputs` maps hook names to target object names, e.g.:
        {"Surface": "Ground", "Collision": "Walls"}
    Each creates an Object socket on the container's Group Input
    wired through Object Info → Geometry. If None, creates a single
    default "Surface" hook.
    
    Returns: {"container": name, "object": object_name,
              "modifier": mod_name, "inputs": [...hook names...]}
    """

def list_containers() -> list[dict]:
    """Scan bpy.data.node_groups for synthgen_type == 'container'.
    Returns: [{"name": ..., "object": ..., "assets": [...]}]
    """

def add_asset(container: str, asset_name: str,
              after: str | None = None) -> dict:
    """Load asset from any registered Blender Asset Library if not already
    in bpy.data.node_groups. Searches ALL libraries — SynthGen's custom
    assets and Blender's built-in GN library. SynthGen library takes
    precedence on name collision.
    Inserts into geometry chain after `after` (or appends to end).
    Tags node with synthgen_asset.
    Returns: {"node": node_name, "position": int, "inputs": [...]}
    """

def remove_asset(container: str, node_name: str) -> dict:
    """Remove sub-group node, re-wire geometry around it.
    Returns: {"removed": node_name, "chain": [...remaining...]}
    """

def list_assets(container: str) -> list[dict]:
    """Trace geometry DAG from Group Input to Group Output.
    Returns ordered list of assets with node names, types, positions.
    """

def find_container(asset_node_group: str) -> str | None:
    """Reverse lookup: which container uses this asset node group?
    Scans all containers for sub-group nodes referencing the given tree.
    """

def reorder_asset(container: str, node_name: str,
                  after: str | None = None) -> dict:
    """Move asset to a new position in the chain. Re-wires geometry.
    after=None → move to first position (right after Group Input).
    """
```

**Linear chain internals (Stage 1 scope):**

```python
def _trace_chain(container_ng) -> list[Node]:
    """Follow geometry links from Group Input to Group Output.
    Returns nodes in evaluation order, skipping Group Input/Output."""

def _splice_after(container_ng, new_node, after_node):
    """Insert new_node into the geometry chain after after_node.
    Breaks the existing link, creates two new links."""

def _splice_out(container_ng, node):
    """Remove node from the geometry chain.
    Re-wires upstream output → downstream input."""
```

**Tests:** Offline unit tests using `unittest.mock` for bpy, verifying the
splice logic, tagging, and idempotency.

**Verify:**
- [ ] `create()` produces tagged, empty container with Geometry in/out
- [ ] `add_asset()` loads node group, inserts into chain, tags node
- [ ] `remove_asset()` re-wires around removed node
- [ ] `list_assets()` returns correct order
- [ ] `find_container()` reverse lookup works
- [ ] `list_containers()` discovers tagged containers
- [ ] Same asset type can be added multiple times
- [ ] `create()` is idempotent on an object that already has a container

### Stage 2: MCP tool wrappers

**Goal:** Expose container operations as MCP tools, callable by the agent.

**Tools (in `mcp/containers.py`):**

| Tool | Maps to | Description |
|---|---|---|
| `create_container` | `containers.create()` | Create procedural context on object |
| `add_asset` | `containers.add_asset()` | Add asset to container chain |
| `remove_asset` | `containers.remove_asset()` | Remove asset, re-wire |
| `list_containers` | `containers.list_containers()` | Discover all containers |
| `list_container_assets` | `containers.list_assets()` | What's in a container |
| `reorder_asset` | `containers.reorder_asset()` | Move asset in chain |

**MCP resources (scene topology):**

The agent discovers live scene state through navigable MCP resources:

```
synthgen://scene/containers/              → all containers
synthgen://scene/containers/{object}/     → container on object
synthgen://scene/containers/{object}/{container}/  → assets in context
```

These resources reflect the same hierarchy the user sees in the N-panel
dynamic menu: `SynthGen → in_scene → <object> → <container> → [assets]`.
One data source (`list_containers` + `list_assets`), two views.

**Integration:** Tools registered alongside existing MCP tools. The agent's
MCP instructions updated to describe the container workflow.

**Verify:**
- [ ] Agent can create container, add assets, configure params, list results
- [ ] Round-trip: agent creates → user sees in Blender → agent queries → correct
- [ ] Error handling: missing object, missing asset, invalid position
- [ ] MCP resources reflect scene topology accurately
- [ ] N-panel menu mirrors the same hierarchy as MCP resources

### Stage 3: DAG support

**Goal:** Replace linear chain assumption with full DAG tracing. Support
branching (one asset feeding multiple downstream) and merging (Join Geometry).

1. Replace `_trace_chain()` with `_trace_dag()`:
   - Walk geometry links as a directed graph, not a linear list
   - Return a DAG structure (nodes + edges), not a flat list
   - Handle multiple geometry outputs from a single node
   - Handle Join Geometry nodes that merge streams
2. Update `add_asset()`:
   - `after` parameter accepts a specific output socket for branching
   - New `before` parameter for inserting before a specific node
3. Update `remove_asset()`:
   - Handle nodes with multiple downstream consumers
   - Re-wire all downstream connections to the removed node's upstream
4. Update `list_assets()`:
   - Return DAG structure with parent/child relationships
   - Topological sort for display order
5. Add `branch_asset()`:
   - Split a geometry stream: existing link + new branch from same output
6. Add `join_assets()`:
   - Insert a Join Geometry node to merge two streams

**Verify:**
- [ ] Linear chains still work (DAG is a superset)
- [ ] Branch: one scatter feeding two different instancers
- [ ] Merge: two branches joining via Join Geometry
- [ ] Remove from a branch point re-wires correctly
- [ ] `list_assets()` shows DAG topology

### Stage 4: Addon UI

**Goal:** N-panel UI for container management. Users can do everything the
agent can, through Blender's interface.

1. **Container panel** (in the GN modifier section or a SynthGen tab):
   - Shows container name, target object
   - List of assets in chain order (DAG-aware)
   - [+ New Container] button on objects without one
2. **Asset management:**
   - [+ Add Asset] → opens filtered Asset Browser or dropdown
   - [× Remove] per asset
   - [↕] drag-to-reorder (linear) or connection management (DAG)
3. **Asset configuration:**
   - Clicking an asset in the panel selects/opens its sub-group node
   - Parameters visible at the sub-group level (not bubbled to panel)
4. **Auto-register asset library:**
   - On addon enable, register `assets/` as a Blender Asset Library
   - On addon disable, optionally unregister

**Verify:**
- [ ] User can create container from panel
- [ ] User can add/remove assets from panel
- [ ] User sees assets added by agent (shared state)
- [ ] Agent sees assets added by user (shared state)
- [ ] Asset Browser shows SynthGen catalog with drag-and-drop

## Risks

| Risk | Mitigation |
|---|---|
| `bpy.ops.asset.catalog_new` requires UI context | Write `blender_assets.cats.txt` directly for headless; operator for interactive |
| Custom properties lost on node group duplication | Test: duplicate container, verify tags survive. If not, re-tag on mutation. |
| DAG tracing complexity with nested groups | Stage 3 scoped separately; linear chain (Stage 1) covers 90% of use cases |
| Asset Library path is absolute in Blender prefs | Use relative path from addon directory; document in install instructions |
| Asset Browser drag-and-drop bypasses container | Documented behavior: drag-and-drop creates a standalone Group node, not inside a container. The panel is the managed path. |

## Key files

| File | Role |
|---|---|
| `src/synthgen/containers.py` | Core module — container lifecycle, chain/DAG wiring |
| `mcp/containers.py` | MCP tool wrappers |
| `addon/synthgen_mcp/panels/containers.py` | N-panel UI (Stage 4) |
| `assets/blender_assets.cats.txt` | Catalog hierarchy definition |
| `scripts/mark_assets.py` | Asset registration script |
| `knowledge/asset_composition.md` | Architecture reference |
| `knowledge/well_known_attributes.md` | Attribute contract |

## Open questions

- [ ] Should `create_container` automatically add a default asset (e.g., the
      last-used asset type), or always start empty?
- [ ] How should the addon handle third-party SynthGen-compatible assets?
      (User drops a `.blend` in the library directory — does it just work?)
- [ ] Should containers support "presets" — saved asset+parameter combinations
      that can be instantiated as a template?
- [ ] How does the container interact with Blender's modifier stack? If the
      object has other (non-SynthGen) modifiers, what's the expected ordering?
- [ ] Should `list_assets()` return parameter values for each asset, or just
      the asset identity and position? (Parameter inspection is already available
      via `get_modifier_inputs` / `list_tree_nodes`.)
- [x] Asset discovery: SynthGen library takes precedence on name collision
      (locked in cross-catalog discovery decision above).

## Definition of done

### Stage 0
- [ ] `blender_assets.cats.txt` committed in `assets/`
- [ ] `scripts/mark_assets.py` committed and tested
- [ ] Scatter on Surface and Instance on Points marked as assets in `scatter.blend`
- [ ] Asset Browser discovery verified manually

### Stage 1
- [ ] `src/synthgen/containers.py` with full API
- [ ] Offline tests for splice logic and tagging
- [ ] Headless integration test: create container, add 2 assets, remove 1, verify chain

### Stage 2
- [ ] MCP tools registered and callable
- [ ] Agent can compose a pipeline end-to-end via MCP
- [ ] MCP instructions updated

### Stage 3
- [ ] DAG tracing replaces linear chain
- [ ] Branch and merge operations work
- [ ] All Stage 1 tests still pass (linear is a DAG subset)

### Stage 4
- [ ] N-panel shows containers and assets
- [ ] Shared authoring verified: user adds via panel, agent sees via MCP (and vice versa)
- [ ] Asset library auto-registered on addon enable
