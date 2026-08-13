# POR — MCP Layer (Phase 3)

## Goal

Build the synthgen MCP server — a layered tool surface where procedural authoring
tools are first-class and grounded against extracted schemas, imperative setup tools
are available for component authoring, and the agent's queries fuse bpy introspection
with our graph traversal algorithms automatically.

This is not a generic Blender MCP. It is a **composite query engine** (bpy for ground
truth + our graph for relationship reasoning) with an MCP interface on top.

## Architecture

### What we are / are not building

**We build:** a synthgen MCP server (Python, stdio) that owns the four-layer tool
surface: Setup, Procedural, Introspect, Sweep. Every tool validates inputs, calls into
bpy and/or the LiveGraph, and returns structured results.

**We compose with:** an existing Blender MCP (e.g. `ahujasid/blender-mcp`) for
transport — the WebSocket-inside-Blender problem is solved infrastructure. Our server
proxies bpy calls through the composed transport and owns everything above it:
validation, grounding, graph reasoning, sweep orchestration.

**We do not build:** WebSocket server inside Blender, raw `execute_python` dispatch,
render-pipeline plumbing. Those belong to the transport MCP.

### The composite query engine

The agent sees one tool surface. Under the hood, each tool may call:

- **bpy** (via the composed transport) — for existence checks, mutations, property
  reads, depsgraph cooking. This is ground truth for "what exists."
- **LiveGraph** — for relationship reasoning bpy can't do: cross-domain joins
  (GN→shader bridge), impact chains (object→modifier→tree→bridge→material), driver
  topology, qualified path addressing across Blender's siloed namespaces.
- **Extracted schema** — for static validation of node types, socket identifiers,
  property enums. Committed per Blender version, never changes at runtime.

A single tool call (e.g. `attribute_trace("rust")`) may fuse all three: cook the
depsgraph (bpy), walk the bridge edges (LiveGraph), validate node types (schema).

### Graph freshness

**Tier-1 edges are always fresh** — LiveGraph queries bpy on demand (lazy, pull-based).
No cache, no staleness.

**Tier-2 edges (attr_bridge) use dirty-flag invalidation.** Any Layer 2 tool that
modifies a GN tree or shader tree sets a dirty flag. The next Layer 3 query that needs
tier-2 data auto-resolves (cooks depsgraph, re-joins bridges). The agent never thinks
about freshness — we handle it behind the MCP boundary.

**No automatic graph history.** The graph is always current state. For before/after
comparisons, the agent explicitly snapshots (`graph.snapshot`). For reproducibility,
Layer 4 tools automatically save a provenance snapshot alongside each render output.

## Tool surface — four layers

### Layer 1: Scene Setup (imperative, component authoring)

Create the components that feed the procedural system. These are one-time authoring
ops — they produce fixed inputs, not sweepable outputs.

| Tool | What it does |
|---|---|
| `create_object` | Add mesh, empty, curve, light, camera |
| `edit_mesh` | Modify geometry — extrude, bevel, loop cut |
| `create_material` | Create a material, assign to object |
| `import_asset` | Import FBX/OBJ/USD/textures from disk |
| `configure_render` | Set engine, resolution, passes, output paths |
| `set_parent` | Parent/unparent objects, organize collections |
| `add_keyframes` | Set keyframes, animation data, NLA actions |

Tool descriptions embed procedural-first guidance: "Creates a mesh component for use
as input to procedural systems. For variation across a dataset, use Layer 2 tools."

### Layer 2: Procedural Authoring (node graphs, first-class + grounded)

Every node/socket reference validated against the extracted schema before it reaches
bpy. This is the layer that makes synthgen different from a generic MCP.

| Tool | Context | What it does |
|---|---|---|
| `add_gn_modifier` | GN | Add GN modifier, create/assign node group |
| `add_node` | GN / Shader / Comp | Add node by grounded type ID |
| `link_sockets` | GN / Shader / Comp | Connect sockets by grounded identifiers |
| `set_node_property` | GN / Shader / Comp | Set node enum/property |
| `set_socket_default` | GN / Shader / Comp | Set socket default value |
| `expose_parameter` | GN | Add socket to group interface (sweepable) |
| `add_driver` | any | Add driver expression linking properties |
| `wire_attr_bridge` | GN→Shader | Helper: Store Named Attr + Attribute node, type-checked |
| `wire_compositor_pass` | Comp | Helper: render pass → File Output for ground truth |

**Grounding enforcement (non-negotiable):**
- **Static:** "does this node type exist? does it have this socket?" — rejected at the
  MCP boundary with "did you mean X?" suggestions from the schema.
- **Dynamic:** "does this specific node exist in this tree?" — validated by bpy call
  before mutation.
- Both levels enforced, not advisory. Hallucinated identifiers never reach bpy.

**Mutation bookkeeping:** every Layer 2 tool that modifies a GN or shader tree sets the
tier-2 dirty flag so the next Layer 3 query auto-resolves.

### Layer 3: Introspection (read-only, fuses bpy + graph)

Query tools that compose bpy introspection with our traversal algorithms. The agent
sees one API; under the hood it's a hybrid query.

| Tool | What it does |
|---|---|
| `schema.query` | Node type lookup, socket listing, keyword search (extracted schema) |
| `graph.walk` | Traverse scene graph — `reachable`, `path`, `neighbors` |
| `graph.impact_set` | "If I change X, what breaks?" — reverse reachability |
| `graph.attribute_trace` | Find all producers/consumers of a named attribute |
| `graph.snapshot` | Serialize a subgraph to JSON for diffing / provenance |
| `verify.attribute_exists` | Cook depsgraph, confirm attribute on evaluated object |

### Layer 4: Sweep & Execute (render, batch, labels)

| Tool | What it does |
|---|---|
| `set_parameter` | Set GN interface value, material property, or driver input |
| `render` | Render current frame / frame range, return output path |
| `sweep` | Batch iterate over parameter grid (seeds × params), render each |
| `export_labels` | Extract ground truth — seg masks, depth, normals, bboxes |

`render` and `sweep` automatically save a provenance snapshot of the graph state
alongside each output for reproducibility.

### Escape hatch: `execute_python`

A scoped pass-through to the transport's `execute_blender_code` (ahujasid's tool name)
or direct `exec()` (headless). Available for cases our structured tools don't cover
yet. Requirements:

- Must include a `reason` string (logged)
- Tagged as **ungrounded** — the introspection layer knows graph state may have changed
  outside its view, triggers a full re-resolve on next Layer 3 query
- Advisory security boundary, not blocked

## Transport + install shape

### `ahujasid/blender-mcp` — what we're composing with

Verified against v1.8.0 source (PyPI wheel + `addon.py` from GitHub main). Key facts:

- **Transport:** plain TCP socket (not WebSocket), JSON-framed, default `localhost:9876`.
  Request: `{"type": "<cmd>", "params": {...}}`. Response: `{"status": "success"|"error",
  "result": {...}}`.
- **Key tool:** `execute_blender_code(code)` — bare `exec()` with `{"bpy": bpy}` namespace,
  captures stdout. No sandboxing. This is how we proxy bpy calls.
- **Other tools:** `get_scene_info`, `get_object_info`, `get_viewport_screenshot`, plus
  Poly Haven / Sketchfab / Hyper3D integrations (irrelevant to us).
- **Their server SDK:** `mcp[cli]` (Anthropic reference SDK, FastMCP helper), stdio.
  Same base SDK we're using — compatible ecosystem.
- **Serialization constraint:** `threading.Lock` serializes send+receive per connection.
  One in-flight command at a time. Our `TransportBackend` must respect this.
- **Install:** `uvx blender-mcp` (MCP server). Addon is a standalone `.py` file installed
  manually via Blender preferences.

**Critical constraint: no headless mode.** The addon checks `bpy.app.background` and
refuses to start its socket server. Our project's workflow (`blender -b -P script.py`)
is incompatible with this addon. This means:

- **GUI sessions** (interactive authoring via Claude Code / Cursor): compose with
  ahujasid's addon socket — works as expected.
- **Headless sessions** (CI, batch extraction, testing): need a different transport —
  direct `bpy` import in-process, or our own thin headless addon.

### `TransportBackend` — two runtime modes

The synthgen MCP server is the **same code** in both modes. Only the transport
backend — how `execute_python(code)` is fulfilled — changes.

**Mode 1: Outside Blender (SocketTransport) — interactive authoring**

```
Claude Code / Cursor
    ↕ stdio (MCP protocol)
synthgen-mcp  (standalone Python process)
    ↕ TCP socket localhost:9876
ahujasid addon  (inside Blender GUI)
    ↕ exec()
bpy
```

- Blender runs with GUI, ahujasid addon active and listening
- Claude Code launches `synthgen-mcp` as a separate subprocess
- synthgen-mcp proxies bpy calls over the TCP socket
- Use case: interactive sessions — user is working in Blender, agent assists

**Mode 2: Inside Blender (DirectBpyTransport) — headless batch**

```
Claude Code / Cursor
    ↕ stdio (MCP protocol)
blender -b -P mcp/server.py  (bpy in same process)
```

- Claude Code launches Blender headless with the MCP server as a script
- `import bpy` works directly — no socket, no addon, no GUI
- Use case: CI, batch extraction, sweep, testing

**Auto-detection at startup:**
- `BLENDER_HOST`/`BLENDER_PORT` env vars set → `SocketTransport`
- `bpy` importable (running inside Blender) → `DirectBpyTransport`
- Neither → fail with clear message

```
TransportBackend (ABC)
    execute_python(code: str) → dict
    get_blender_version() → tuple[int, int, int]

├── SocketTransport
│   Sends {"type": "execute_code", "params": {"code": code}}
│   over TCP to ahujasid addon. Respects serialization lock.
│
└── DirectBpyTransport
    Calls exec(code, {"bpy": bpy}) in-process.
    Returns captured stdout as result.
```

All tools call `transport.execute_python(code_string)`. They don't know or care
which backend is active. The agent sees the same tools, same results, same
experience in both modes.

MCP clients load both synthgen and the transport MCP (in Mode 1). The agent sees
both toolsets. Synthgen tools are preferred for grounded work; the transport MCP's
raw tools are the escape hatch.

### Version-aware schema resolution

The schema directory is already version-bucketed (`data/schemas/blender-5.2/`,
`data/schemas/houdini-22.0/`, etc.). Currently `schema.query` hardcodes
`BLENDER_DIR = "blender-5.2"`. Phase 3 makes this dynamic:

1. **Auto-detect at startup.** When the MCP server connects to Blender via the
   transport layer, it queries `bpy.app.version` (e.g. `(5, 2, 0)`) and resolves the
   matching schema directory (`data/schemas/blender-5.2/`).
2. **Fallback chain.** If an exact match isn't found, fall back to the closest
   available version, then to `$SYNTHGEN_SCHEMA_DIR`, then fail with a clear message
   telling the user to run the extractor for their Blender version.
3. **Grounding validates against the connected Blender's schema**, not a hardcoded one.
   If the user upgrades Blender, they re-run the extractor and the MCP picks up the
   new schemas automatically.
4. **Extractor is a first-class tool.** `python -m synthgen.extract.node_schema`
   (run inside the target Blender) generates the schema files. This is documented as
   part of the "add a new Blender version" workflow.

This means the tool surface works across Blender versions without code changes — only
the schema data changes.

### Install shape

**Thin addon, fat package.** A lightweight Blender addon:
- Installs/imports the `synthgen` pip package into Blender's Python
- Registers the transport endpoint (if we build our own; otherwise the composed MCP
  handles this)
- Survives Blender updates (lives in user prefs, not install dir)

All logic stays in the pip package, which is testable offline without Blender
(`pip install -e ".[dev]" && pytest`).

## Security boundaries

**Advisory with classification, not enforced in Phase 3.**

Every tool call is tagged with its layer. Boundary crossings are logged:
- Layer 1 (Setup): can mutate scene state
- Layer 2 (Procedural): should only modify node graphs
- Layer 3 (Introspect): read-only
- Layer 4 (Sweep): triggers renders, reads outputs

The more important boundary is **grounded vs. ungrounded**: every tool call is tagged
as schema-validated or escape-hatch. Ungrounded operations trigger a full graph
re-resolve on next query.

Enforcement can be added later if multi-user or untrusted-agent scenarios arise — the
classification is the investment.

## Phased delivery

### Phase 3a — Read-only MCP (minimum viable)

Expose the introspection tools over MCP. No mutations, no sweep. This is the
lowest-risk starting point and immediately useful — an agent with schema.query +
graph.walk + impact_set can reason about any existing scene.

| Tool | Source |
|---|---|
| `schema.query` | wraps `synthgen.schema.query` CLI |
| `graph.walk` | wraps `traverse.reachable`, `traverse.path`, `LiveGraph.neighbors` |
| `graph.impact_set` | wraps `traverse.impact_set` |
| `graph.attribute_trace` | wraps `traverse.attribute_trace` |
| `graph.snapshot` | wraps snapshot materialization |
| `verify.attribute_exists` | new: cook depsgraph + check evaluated attributes |

**Definition of done (3a):**
- [ ] MCP server (Python, stdio, reference `mcp` SDK) exposing 6 read-only tools
- [ ] Composes with `ahujasid/blender-mcp` via `TransportBackend` abstraction
- [ ] Version-aware schema resolution: auto-detect from `bpy.app.version`, fallback chain
- [ ] `schema.query` no longer hardcodes `BLENDER_DIR` — resolves dynamically
- [ ] Tools return structured JSON, not raw bpy output
- [ ] Integration test: load a `.blend`, query `impact_set` through MCP, verify result
- [ ] `pytest` green (offline tests for schema.query, snapshot-based graph tests)
- [ ] ROADMAP updated
- [ ] Commits logical, not pushed without asking

### Phase 3b — Procedural authoring tools (Layer 2)

Add the grounded mutation tools. Each tool validates against the schema, executes via
bpy, and sets the tier-2 dirty flag.

**Definition of done (3b):**
- [ ] Layer 2 tools implemented: `add_node`, `link_sockets`, `set_node_property`,
      `set_socket_default`, `expose_parameter`, `add_driver`
- [ ] Helper recipes: `wire_attr_bridge`, `wire_compositor_pass`
- [ ] Grounding enforcement: static (schema) + dynamic (bpy existence) — hallucinated
      identifiers rejected with suggestions
- [ ] Dirty-flag invalidation: Layer 2 mutation → auto-resolve on next Layer 3 query
- [ ] Integration test: build a GN scatter + shader bridge through MCP tools, verify
      with `attribute_trace`
- [ ] `pytest` green
- [ ] Commits logical, not pushed without asking

### Phase 3c — Setup + Sweep (Layers 1 & 4)

Add imperative authoring (Layer 1) and batch execution (Layer 4). These are thinner
wrappers — Layer 1 proxies to bpy via transport, Layer 4 adds sweep orchestration and
provenance snapshots.

**Definition of done (3c):**
- [ ] Layer 1 tools: `create_object`, `edit_mesh`, `create_material`, `import_asset`,
      `configure_render`, `set_parent`, `add_keyframes`
- [ ] Layer 4 tools: `set_parameter`, `render`, `sweep`, `export_labels`
- [ ] Provenance snapshot saved alongside each render output
- [ ] Agent guidance embedded in tool descriptions (procedural-first nudges)
- [ ] End-to-end test: author a simple scene, wire procedural variation, sweep 10
      seeds, verify outputs + provenance
- [ ] ROADMAP Phase 3 marked done
- [ ] Commits logical, not pushed without asking

## Decisions locked

- **Compose, don't build transport.** Start with `ahujasid/blender-mcp` for GUI
  sessions (TCP socket on localhost:9876). `DirectBpyTransport` for headless. Both
  behind a `TransportBackend` ABC so the tool surface doesn't know or care.
- **Grounding enforced, not advisory.** Hallucinated node/socket identifiers rejected
  at the MCP boundary. Both static (schema) and dynamic (bpy) validation.
- **Reference MCP SDK.** Use Anthropic's `mcp` Python SDK for ecosystem
  compatibility and stdio transport.
- **Start atomic, design for diff.** Layer 2 tools are individual ops (add_node,
  link_sockets), not graph-diffs. Transaction boundaries can be added later.
- **Thin addon, fat package.** Blender addon is a shim; all logic in the pip package.
- **Security boundaries advisory.** Tagged and logged, not enforced. Grounded vs.
  ungrounded is the primary boundary.
- **No automatic graph history.** Current state only. Explicit snapshots on demand,
  provenance snapshots at render time.
- **Dirty-flag freshness.** Tier-2 edges auto-resolve on next read after any mutation.
  Agent never manages freshness.
- **Procedural-first guidance in tool descriptions.** Layer 1 tools explicitly direct
  agents toward Layer 2 for variation work.
- **Version-aware schemas.** Schema resolution auto-detects from connected Blender
  version. No hardcoded version in code. New Blender versions supported by running
  the extractor — no code changes needed.

## File layout (expected)

```
mcp/
  server.py               ← MCP server entry point (stdio)
  tools/
    schema.py              ← schema.query tool
    graph.py               ← graph.walk, impact_set, attribute_trace, snapshot
    verify.py              ← verify.attribute_exists
    procedural.py          ← add_node, link_sockets, etc. (Phase 3b)
    setup.py               ← create_object, edit_mesh, etc. (Phase 3c)
    sweep.py               ← set_parameter, render, sweep, export_labels (Phase 3c)
  transport.py             ← proxy layer to composed Blender MCP
  grounding.py             ← schema + bpy validation logic
dev_tasks/002_mcp_layer/
  POR.md                   ← this file
```

## Resolved references

- **Compositor 5.x path:** `scene.compositing_node_group` (not `scene.node_tree`) —
  validated in Phase 2. Layer 2 tools must use this accessor.
