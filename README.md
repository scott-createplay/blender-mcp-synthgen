# blender-synthgen-mcp

Procedural **3D synthetic-data** toolkit for Blender — grounded node schemas, a lazy
scene-graph walker, and a Houdini→Blender knowledge base, delivered as a **self-contained
Blender addon** with an MCP server built in.

## Quick Install (Blender addon)

1. **Download** the latest `synthgen_mcp.zip` from releases (or build it yourself — see below)
2. **Install** in Blender: Edit → Preferences → Add-ons → Install from Disk → select the zip
3. **Enable** "Synthgen MCP" — first enable installs dependencies (~15s one-time)
4. **Connect** from your IDE:

   **Claude Code / Cursor / VS Code** — add to your MCP config:
   ```json
   {"synthgen": {"url": "http://localhost:8400/sse"}}
   ```

That's it. The addon runs an SSE MCP server inside Blender on port 8400. Your IDE connects
to it and gets 33 grounded tools for procedural 3D work.

### N-panel controls

In the 3D viewport sidebar (N) → "Synthgen MCP" tab:
- **Start/Stop** — toggle the MCP server
- **Copy MCP Config** — copies the connection JSON to your clipboard
- **Server status** — shows running state and port

### Change the port

Edit → Preferences → Add-ons → Synthgen MCP → Port (default 8400)

## What's inside

The addon bundles:
- **33 MCP tools** across 5 layers (setup, procedural authoring, graph introspection, pipeline, verification)
- **Grounding data** — extracted node schemas for Blender 5.2 (Geometry Nodes, Shader, Compositor)
- **Main-thread executor** — marshals all bpy calls safely from the MCP background thread

### Tool layers

| Layer | Tools | Purpose |
|---|---|---|
| **Setup** | `create_object`, `create_material`, `assign_material`, `set_parent`, `configure_render`, `import_asset`, `edit_mesh`, `add_keyframes` | Scene building blocks |
| **Procedural** | `add_gn_modifier`, `add_node`, `link_sockets`, `set_node_property`, `set_socket_default`, `expose_parameter`, `add_driver`, `wire_attr_bridge`, `wire_compositor_pass` | Node graph authoring with grounded identifiers |
| **Introspection** | `graph_nodes`, `graph_neighbors`, `graph_reachable`, `graph_impact_set`, `graph_attribute_trace`, `graph_snapshot` | Live scene-graph traversal |
| **Pipeline** | `set_parameter`, `render`, `sweep`, `export_labels` | Parameter sweeps + provenance |
| **Schema** | `schema_find`, `schema_show`, `schema_socket`, `schema_setting` | Query node schemas |
| **Verify** | `verify_attribute_exists` | Runtime attribute checks |
| **Escape hatch** | `execute_python` | Direct bpy access (ungrounded) |

## Why this exists

Transport (a Blender MCP) is a commodity. The moat is **version-exact grounding + a
build→verify loop**. LLMs hallucinate node/socket identifiers, so we **extract the real schema
from Blender itself** and give the agent tools to query it — never trusting model memory. The
same idea, one level up, becomes the **scene-graph walker**: a lazy, pull-based view over the
live scene so the agent can traverse real relationships.

Governing principle (see [`knowledge/procedural_paradigm.md`](knowledge/procedural_paradigm.md)):
**derive, don't set.** Native Blender is imperative/destructive; the agent must live on the
procedural island (Geometry Nodes / shader / compositor / drivers), because you **cannot sweep
a hand-edit**, and sweeping a parameter space is the whole job.

## Build from source

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (offline — no Blender needed)
pytest

# Build the addon zip
python scripts/build_addon.py
# → dist/synthgen_mcp.zip
```

### Development mode

For development without rebuilding the zip each time:

1. Set Blender's `BLENDER_USER_SCRIPTS` environment variable to point to the `addon/` directory
2. Or symlink `addon/synthgen_mcp/` into Blender's addons folder

The addon auto-detects whether it's running from source (adds `src/` to path) or from a
built zip (uses bundled files).

## Grounded against

- **Blender 5.2.0 LTS** — Geometry Nodes (360), Shader (118), Compositor (168) node schemas
- **Houdini 22.0.368** — SOP/VOP/COP node schemas (for the crosswalks)

Regenerate for another version with the extractors in `src/synthgen/extract/` (run inside
Blender / `hython`); drop results in `data/schemas/<app-version>/`.

## Schema CLI (standalone)

The schema query tool works without Blender:

```bash
python -m synthgen.schema.query stats
python -m synthgen.schema.query show "Store Named Attribute"
python -m synthgen.schema.query --shader show "Attribute"
python -m synthgen.schema.query --compositor find "Cryptomatte"
```

## Architecture

```
IDE (Claude Code / Cursor / VS Code)
  │
  │  MCP protocol over SSE HTTP
  │
  ▼
Blender addon (synthgen_mcp)
  ├── SSE MCP server (background thread, port 8400)
  ├── Main-thread executor (bpy.app.timers queue)
  ├── 33 grounded tools
  ├── Bundled schema data
  └── N-panel UI
```

See [`ROADMAP.md`](ROADMAP.md) for project status and phase details.

## License

MIT
