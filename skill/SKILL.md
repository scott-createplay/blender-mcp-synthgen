---
name: blender-synthgen
description: Generate 3D synthetic data in Blender the procedural way — grounded Geometry/shader/compositor node knowledge, Houdini→Blender translation, and a build→verify loop. Use when authoring Geometry Nodes / materials / compositor graphs, translating Houdini setups, or building domain-randomized synthetic datasets in Blender.
---

# blender-synthgen

You are driving Blender to build **procedural, reproducible synthetic-data pipelines**:
structural variation from Geometry Nodes, appearance variation from shaders, ground-truth
labels from the compositor — swept over parameters/seeds.

## Governing rule — read `knowledge/procedural_paradigm.md` first
**Derive, don't set.** Author/extend node graphs driven by scene-derived signals; treat
destructive `bpy.ops` scene edits as a last resort. You cannot sweep a hand-edit, and sweeping
is the job.

## Never guess node identifiers — query the grounded schema
Socket *label* ≠ *identifier* (e.g. "Group ID" → `Group Index`; Math has `Value/Value_001/
Value_002`). Before writing bpy that builds a graph, look it up:
```
python -m synthgen.schema.query show "Store Named Attribute"
python -m synthgen.schema.query --shader show "Attribute"
python -m synthgen.schema.query --compositor find "Cryptomatte"
```

## Knowledge base (read the relevant crosswalk before translating)
- `knowledge/procedural_paradigm.md` — the constitution (derive-don't-set, scene signals).
- `knowledge/houdini_to_geonodes.md` — SOP → Geometry Nodes.
- `knowledge/attribute_bridge.md` — GN ↔ shader via named attributes (per-instance variation + labels).
- `knowledge/cop_to_compositor.md` — Houdini COPs (Copernicus) → Blender compositor (passes → masks/depth).
- `knowledge/scene_graph_contexts.md` — cross-context edge model for scene introspection/refactor.

## Build → verify loop
1. Plan in **graphs and fields**: "what signal drives this?" not "what tool changes this?"
2. Look up every node/socket in the schema before wiring it.
3. Build via graph edits (bpy that constructs/rewires nodes), not destructive ops.
4. **Verify across seeds/params**, not one state: confirm attributes exist on the expected
   domain (GN `Named Attribute.Exists`), render a small batch, confirm variation is valid and
   label passes stay pixel-exact. A single rendered frame is never sufficient proof.

## Composability
This runs alongside an existing Blender MCP that provides transport (`execute_python`, render).
This skill supplies the *knowledge + grounding*; execute bpy through that transport.
