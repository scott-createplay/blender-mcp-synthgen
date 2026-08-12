# Scene Graph — context model & edge spec

Design-of-record for the Blender scene-graph extractor. The agent parses a Blender scene into
a **typed multigraph** so it can traverse relationships across the scene to introspect and
(later) refactor. This spec defines *what nodes and edges exist* and *how each is obtained*.

## Thesis: complete up to Blender's own data model

bpy is the same API Blender's UI drives, and every datablock is RNA-introspectable, so
**authorability ⇒ introspectability**: anything a user can construct procedurally (headless),
we can also enumerate — including triggering evaluation and reading the cooked result. The
read surface is as total as the write surface.

Therefore the graph can be **complete up to what Blender can represent** — no more, no less.
That bounds the whole effort and makes it achievable.

## Houdini-context framing

Blender has informal "contexts" analogous to Houdini's networks. In Houdini every context hop
is an explicit node with a path (`op:/…`) — trivially walkable. Blender scatters the same
information across three tiers, and the tier decides how we obtain the edge.

| Houdini | Blender context | Form |
|---|---|---|
| OBJ | scene / objects / collections / view layers | container + props |
| SOP | Geometry Nodes tree | node tree |
| VOP | GN field nodes / shader nodes | embedded subgraph |
| MAT/SHOP | material shader trees | node tree |
| COP | compositor tree | node tree |
| CHOP | drivers | property→property |
| DOP | sim zones / legacy physics | partial |
| LOP | — (USD is import/export only) | **ontological gap** |
| ROP | render settings + File Output | mostly props |
| TOP (PDG) | — | **ontological gap** |

## Edge tiers

- **① Native** — a real datablock pointer. Read directly from the API. State-independent.
- **② Reconstructed** — matched by name/index, not a pointer; Blender computes it at cook time.
  We read the cooked state (same as Blender). State-*dependent* (snapshot-valid).
- **③ Ontological gap** — Blender's data model has no such relationship. Recorded as an
  external/gap node, never fabricated.

## Cross-context edge table

| Edge | Tier | How to obtain (bpy) |
|---|---|---|
| OBJ → SOP | ① | `obj.modifiers[].node_group` (type `NODES`) |
| SOP → OBJ/collection | ① | `ObjectInfo`/`CollectionInfo` node `inputs['Object'/'Collection'].default_value` **and** the value bound on the modifier interface input (see gotcha) |
| OBJ ↔ OBJ | ① | `obj.parent`; `collection.children/objects` |
| any → any (value) | ① | `id.animation_data.drivers[].driver.variables[].targets[].id/.data_path` (check object, material node-tree, GN node-tree, scene animation_data) |
| SOP → MAT (assign) | ① | `SetMaterial` node `inputs['Material']`; `obj.material_slots[].material` |
| group / subnet nesting | ① | `node.node_tree` (recursive); node groups are **shared** datablocks — emit a definition node + usage edges |
| COP → OBJ | ① | `CompositorNodeRLayers.scene / .layer` |
| datablock uses (any) | ① | `bpy.data.user_map()` — reverse-uses for the whole file, near-free |
| **SOP ↔ MAT (attribute bridge)** | ② | shader `ShaderNodeAttribute.attribute_name` (literal) ⟕ **evaluated** geometry `.attributes` ⟕ GN writer nodes (provenance) |
| **MAT ↔ COP (AOV/pass)** | ② | `ShaderNodeOutputAOV.name` + `view_layer.aovs` ⟕ compositor `RLayers` pass name |
| **OBJ ↔ COP (id mask)** | ② | `object.pass_index` / `material.pass_index` ⟕ `CompositorNodeIDMask.index` |
| → USD stage / PDG | ③ | none — outside Blender's model |

> Compositor tree in Blender 5.x is a node-group datablock (`scene.node_tree` was removed —
> use `scene.compositing_node_group`; confirm exact attr at build).

## Tier ② resolution: cook, then read (this is how Blender does it)

Do **not** infer names by parsing node definitions. Evaluate and read the result — Blender's
"geometry spreadsheet after cook":

```python
dg = bpy.context.evaluated_depsgraph_get()
ev = obj.evaluated_get(dg)
realized_attrs = [(a.name, a.domain, a.data_type) for a in ev.data.attributes]   # authoritative
# per-instance (INSTANCER domain) attributes: iterate dg.object_instances, not obj.data
```

The bridge edge is a **join**:
`shader attribute_name (literal)` ⟕ `evaluated .attributes (authoritative names)` ⟕
`GN Store/Capture nodes (static, for provenance)`.

Two things evaluation does **not** give — why we keep the static graph too:
1. **Provenance** — evaluated geometry says `"rust"` exists, not *which* node wrote it. Static
   graph supplies the writer node(s); if ambiguous, a candidate set.
2. **State-dependence** — the names are true for *this* object/params/frame/seed. A shared GN
   group can yield different attributes per object. Mark each ② edge:
   `state_dependent: true`. (Names rarely vary across a sweep — usually only values do — but
   the graph must be honest that ② is a snapshot, not a structural guarantee.)

Lint fallout (a feature): a shader reading `"rust"` that no evaluated object produces = a
**dead bridge**; an AOV emitted but not captured by any view layer = a **dangling pass**.

## The modifier-boundary gotcha

A GN `Object Info` usually gets its object from an **input exposed on the modifier interface**
(`modifier["Socket_N"]`), not the internal node's socket default. Resolving SOP→OBJ edges must
check **both** the internal node defaults **and** the modifier's bound interface inputs — or
every properly-parameterized (i.e. good) setup loses its edges silently.

## Node & edge schema (snapshot JSON)

```jsonc
{
  "nodes": [
    { "id": "OBJ:Willow", "kind": "object", "data": {...} },
    { "id": "OBJ:Willow/MOD:GeometryNodes", "kind": "modifier", ... },
    { "id": "NG:WillowGrowth", "kind": "nodetree_def", ... },
    { "id": "NG:WillowGrowth/NODE:StoreNamedAttribute.001", "kind": "gn_node", ... }
  ],
  "edges": [
    { "src": "...", "dst": "...", "type": "modifier_uses_tree", "tier": 1, "state_dependent": false },
    { "src": "MAT:Bark/NODE:Attribute", "dst": "OBJ:Willow", "type": "attr_bridge",
      "tier": 2, "state_dependent": true, "resolved": true, "attr": "bark_age",
      "provenance": ["NG:WillowGrowth/NODE:StoreNamedAttribute.001"] }
  ]
}
```

**Addressing scheme** (the backbone that makes refactor possible): stable qualified paths —
`OBJ:<obj> / MOD:<mod> / NG:<tree> / NODE:<node> / SOCK_IN:<identifier>`. You can't change what
you can't name.

## Architecture: lazy walker primary, snapshot is a projection

The graph is **not** an ETL dump. Edges are *derivable* from bpy, so the graph is a **lazy,
pull-based view**: a set of edge-generators you *walk*, yielding as you go — the same
pull-based cooking model as Houdini (an edge is "cooked" only when a traversal pulls it).
Static serialization is one *projection* of that walk, not the foundation.

Why walker-primary (esp. for refactoring, not just read):
- **No staleness under mutation** — a cache is wrong the instant the agent edits the scene; a
  live walk is always current. Mandatory if the graph drives refactor, not just introspection.
- **Pay for what you touch** — `impact_set(X)` walks X's neighborhood and stops; never
  serializes the whole file. Scales to any scene size.
- **Full fidelity** — no level-of-detail schema discards data; drill to any property live.
- **Tier-② on demand** — cook-then-read only for the object being queried.

**The protocol** (all algorithms are written against this, backend-agnostic):
```python
neighbors(node_id, edge_types=None) -> Iterator[Edge]   # generator; lazy
resolve(node_id) -> dict                                 # node detail on demand
```
- **Live backend** (bpy, generators query the scene) — primary, always-current.
- **Snapshot backend** = `materialize(walk(all))` — same algorithms, kept only for the
  *offline / diffable* cases (compare two states; analyze with no running Blender).

**Laziness ≠ repeated cost:** memoize within a *graph session* keyed on the depsgraph update
tag; invalidate on scene change. Lazy + cheap-repeat + correct across the agent's own edits.

**Cost of the power:** the live walker needs a running bpy session (couples to the MCP
transport); a static dump can be analyzed offline. For introspect-*and*-refactor, worth it.

Constraints that still hold:
- **Read-only first**; mutation later and as graph-diff ops, never destructive scene commands
  (see `procedural_paradigm.md`).
- **Level-of-detail**: nodes are datablocks + objects + collections + modifiers + node-tree
  nodes + sockets/links + semantic edges. **Never** geometry elements. Scene-summary; expand a
  named tree on demand. (In the walker this is automatic — you only expand what you pull.)
- **Two sources joined**: static graph (structure + provenance) + evaluated attribute
  inventory per object/instance (authoritative names), the latter cooked on demand.

## Companion tooling
- `scene_graph.py` (bpy-backed lazy walker) — implements the protocol: `neighbors()` generators
  for every tier-①/② edge type, per-session memoization keyed on depsgraph updates.
- Traversal algorithms over the protocol — `ancestors/descendants` by edge type, `impact_set`
  (reverse reachability), `attribute_trace` (producers/consumers of an attr), `orphans`,
  `path(a,b)`. Written once; run on either backend.
- `snapshot_scene_graph.py` — `materialize(walk(all))` → JSON, for offline/diff use only.

Related: `attribute_bridge.md` (the ② bridge in prose), `procedural_paradigm.md` (why
read-first / graph-diff), the node schemas (the *type system* this graph is an instance of).
