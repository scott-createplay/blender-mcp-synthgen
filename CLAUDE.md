# CLAUDE.md — blender-synthgen-mcp

Project context + working rules for any Claude agent editing this repo. Keep this concise;
the deep material lives in `knowledge/` and `docs/ONBOARDING.md` — read those, don't duplicate
them here.

## What this is
A Python toolkit + (later) composable MCP that helps an agent generate **3D synthetic data in
Blender procedurally**: structural variation from Geometry Nodes, per-instance appearance from
shaders, ground-truth labels from the compositor — swept over parameters/seeds. It **composes
with** an existing Blender MCP (transport), it does not replace it.

Start here: `README.md` → `ROADMAP.md` → `knowledge/procedural_paradigm.md` →
`knowledge/scene_graph_contexts.md`. For a task handoff, `docs/ONBOARDING.md`.

## Working principles (non-negotiable)
- **Grounding, not memory.** Never guess Blender node/socket ids. Query the extracted schema:
  `python -m synthgen.schema.query show "<node>"` (also `--shader`, `--compositor`). Socket
  *label ≠ identifier*.
- **Derive, don't set.** Author/rewire node graphs; treat destructive `bpy.ops` scene edits as
  a last resort. Read-only first; mutation is graph-diff, never a destructive command.
- **The scene graph is a lazy, pull-based view** over bpy; the JSON snapshot is a projection
  for offline/diff only. Edge tiers: ① native pointer, ② reconstructed via cook-then-read,
  ③ ontological gap (record, never fabricate).
- **Complete up to Blender's data model** — authorability ⇒ introspectability.

## Dev workflow
- Tests are **offline** (no Blender): `pip install -e ".[dev]" && pytest` (or `PYTHONPATH=src
  pytest`). Keep them green; add tests with new code. ~70% of the code needs no Blender.
- Only `scenegraph/backend_bpy.py` (and the extractors) need Blender. Run bpy headless:
  `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b [file.blend] -P script.py`
- Layout: `src/synthgen/{extract,schema,scenegraph}` · `data/schemas/<app-version>/` ·
  `knowledge/` (agent brain) · `skill/SKILL.md` · `mcp/` (Phase 3).

## Conventions
- **Node addressing** (scene graph): stable qualified paths —
  `COL:x` · `OBJ:x` · `OBJ:x/MOD:m` · `NG:t` · `MAT:m` · `<container>/NODE:n`.
- Keep `backend_bpy.py` importable without Blender (guard `import bpy`).
- Grounding data in `data/schemas/*.json` is committed on purpose (version-pinned), not build
  output. Regenerate with the extractors when targeting a new app version.
- Commit in logical steps with clear messages; **don't push without asking.** Don't commit
  tooling state (`.rig/`, caches).

## Gotchas already discovered (see docs/ONBOARDING.md for the full list)
- Blender text-editor datablocks are stale snapshots — edit on disk, Text→Open/Reload.
- Blender **5.x removed `scene.node_tree`** (compositor is `scene.compositing_node_group`);
  `Gamma` compositor node is dead, `Zcombine` alive.
- Resolve tier-② attribute names by **evaluated `.attributes`** (cook-then-read), not by
  parsing node definitions.

## Model
This work is reasoning-heavy (scene-graph semantics, tier-② resolution, Houdini↔Blender
mapping) — prefer a **top-tier Opus** model here, and cheaper tiers for mechanical edits per the
global routing policy in `~/.claude/CLAUDE.md`. Pin the model with `/model` (Claude Code) or the
`model` key in `.claude/settings.json`; set the exact Opus build you want.
