# blender-synthgen-mcp

Procedural **3D synthetic-data** toolkit for Blender — grounded node schemas, a lazy
scene-graph walker, and a Houdini→Blender knowledge base, designed to **compose with existing
Blender MCP servers** rather than replace them.

The goal is not "an agent that knows Geometry Nodes." It's an agent that generates **synthetic
training data**: procedural geometry for structural variation + per-instance shading variation
+ compositor passes as ground-truth labels — i.e. domain randomization, driven by parameters
and seeds, reproducibly.

## Why this exists (the thesis)

Transport (a Blender MCP) is a commodity. The moat is **version-exact grounding + a
build→verify loop**. LLMs hallucinate node/socket identifiers, so we **extract the real schema
from Blender itself** and give the agent tools to query it — never trusting model memory. The
same idea, one level up, becomes the **scene-graph walker**: a lazy, pull-based view over the
live scene so the agent can traverse real relationships to introspect and (later) refactor.

Governing principle (see [`knowledge/procedural_paradigm.md`](knowledge/procedural_paradigm.md)):
**derive, don't set.** Native Blender is imperative/destructive (like Maya); Houdini is
declarative dataflow. Blender bolted a procedural island (Geometry Nodes / shader / compositor
/ drivers) onto an imperative app — the agent must live on that island, because you **cannot
sweep a hand-edit**, and sweeping a parameter space is the whole job.

## The four components

| Component | Path | What it is |
|---|---|---|
| **Python package** | `src/synthgen/` | extractors, schema query, scene-graph walker |
| **Grounding data** | `data/schemas/` | extracted node schemas, versioned by app version |
| **Knowledge base** | `knowledge/` | the agent's brain — paradigm + Houdini↔Blender crosswalks |
| **MCP layer** | `mcp/` | thin composable server (Phase 3) — high-level tools over the package |

## Composability

`blender-synthgen-mcp` is an **additional, composable MCP** that runs alongside an existing
Blender MCP (e.g. [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp) or the
official one). The existing server owns low-level transport (`execute_python`, render, scene
info); synthgen owns the high-level semantic tools (`schema.query`, `scenegraph.impact_set`,
`attribute_trace`). The core logic is a bpy-side Python library, so it's transport-agnostic —
runnable via an existing MCP's `execute_python`, headless `pip install bpy`, or the GUI.

## Grounded against

- **Blender 5.2.0 LTS** — Geometry Nodes (360), Shader (118), Compositor (168) node schemas.
- **Houdini 22.0.368** — SOP/VOP/COP(Copernicus)/COP2 node schemas (for the crosswalks).

Regenerate for another version with the extractors in `src/synthgen/extract/` (run inside
Blender / `hython`); drop results in `data/schemas/<app-version>/`.

## Quickstart

```bash
# query the grounded Blender schema (no Blender needed — reads data/schemas/)
python -m synthgen.schema.query stats
python -m synthgen.schema.query show "Store Named Attribute"
python -m synthgen.schema.query --shader show "Attribute"
python -m synthgen.schema.query --compositor find "Cryptomatte"

# tests (offline)
pip install -e ".[dev]" && pytest
```

## Status

Graduated from a grounded design spike into a repo. See
[`ROADMAP.md`](ROADMAP.md) — Phases 0–1 (scaffold + grounded schema tooling) are in; the
scene-graph walker, MCP layer, and synthetic-data pattern atlas are next.

## License

MIT (placeholder — change if you prefer).
