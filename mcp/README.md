# MCP layer (Phase 3)

Thin, **composable** MCP server exposing high-level synthgen tools over the Python package.
Runs *alongside* an existing Blender MCP (e.g. `ahujasid/blender-mcp` or the official server),
which owns low-level transport (`execute_python`, render, scene info). MCP clients (Claude Code,
Cursor) load both; the agent sees both toolsets.

Planned tools (all read-only first):
- `schema.query`        — grounded node lookup (wraps `synthgen.schema.query`)
- `scenegraph.neighbors` / `scenegraph.impact_set` / `scenegraph.attribute_trace`
- `scenegraph.snapshot` — materialize a subgraph to JSON for diffing

Not built yet. Gated on the transport + security-posture decision (arbitrary code execution) —
see ROADMAP Phase 3. Until then, the package is usable via an existing MCP's `execute_python`
or headless `bpy`.
