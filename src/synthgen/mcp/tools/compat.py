"""Version-aware code-generation helpers.

Pure functions: (version_tuple, ...) -> str.  No bpy import, no Blender
dependency, fully offline-testable.  Structured tools call these at
code-gen time to emit clean, branchless Python for the target Blender version.
"""

from __future__ import annotations


def _is_5x(ver: tuple[int, ...]) -> bool:
    return ver >= (5, 0, 0)


# ---------------------------------------------------------------------------
# Modifier input access
# ---------------------------------------------------------------------------

def emit_read_input(ver: tuple[int, ...], mod_var: str, ident_expr: str) -> str:
    """Return an expression string that reads a modifier input value."""
    if _is_5x(ver):
        return f"{mod_var}.properties.inputs[{ident_expr}]['value']"
    return f"{mod_var}[{ident_expr}]"


def emit_write_input(
    ver: tuple[int, ...],
    mod_var: str,
    ident_expr: str,
    value_expr: str,
) -> str:
    """Return a statement string that writes a modifier input value."""
    if _is_5x(ver):
        return f"{mod_var}.properties.inputs[{ident_expr}]['value'] = {value_expr}"
    return f"{mod_var}[{ident_expr}] = {value_expr}"


def emit_iter_inputs(ver: tuple[int, ...], mod_var: str) -> str:
    """Return a code block that builds ``inputs`` list.

    Each entry is ``{"identifier": ..., "name": ..., "type": ...,
    "value": ..., "attribute_name": ...}``.
    """
    if _is_5x(ver):
        return (
            f"inputs = []\n"
            f"if {mod_var}.node_group:\n"
            f"    for _item in {mod_var}.node_group.interface.items_tree:\n"
            f"        if hasattr(_item, 'identifier') and _item.in_out == 'INPUT':\n"
            f"            _ident = _item.identifier\n"
            f"            try:\n"
            f"                _prop = {mod_var}.properties.inputs[_ident]\n"
            f"                _val = _prop['value']\n"
            f"                if hasattr(_val, '__len__'):\n"
            f"                    _val = list(_val)\n"
            f"                _attr = _prop.get('attribute_name', '')\n"
            f"                inputs.append({{\n"
            f"                    'identifier': _ident,\n"
            f"                    'name': _item.name,\n"
            f"                    'type': _item.bl_socket_idname,\n"
            f"                    'value': _val,\n"
            f"                    'attribute_name': _attr,\n"
            f"                }})\n"
            f"            except (KeyError, TypeError):\n"
            f"                inputs.append({{\n"
            f"                    'identifier': _ident,\n"
            f"                    'name': _item.name,\n"
            f"                    'type': _item.bl_socket_idname,\n"
            f"                    'value': None,\n"
            f"                    'attribute_name': '',\n"
            f"                }})\n"
        )
    return (
        f"inputs = []\n"
        f"if {mod_var}.node_group:\n"
        f"    for _item in {mod_var}.node_group.interface.items_tree:\n"
        f"        if hasattr(_item, 'identifier') and _item.in_out == 'INPUT':\n"
        f"            _ident = _item.identifier\n"
        f"            try:\n"
        f"                _val = {mod_var}[_ident]\n"
        f"                if hasattr(_val, '__len__'):\n"
        f"                    _val = list(_val)\n"
        f"                inputs.append({{\n"
        f"                    'identifier': _ident,\n"
        f"                    'name': _item.name,\n"
        f"                    'type': _item.bl_socket_idname,\n"
        f"                    'value': _val,\n"
        f"                    'attribute_name': '',\n"
        f"                }})\n"
        f"            except (KeyError, TypeError):\n"
        f"                inputs.append({{\n"
        f"                    'identifier': _ident,\n"
        f"                    'name': _item.name,\n"
        f"                    'type': _item.bl_socket_idname,\n"
        f"                    'value': None,\n"
        f"                    'attribute_name': '',\n"
        f"                }})\n"
    )


# ---------------------------------------------------------------------------
# Compositor tree access
# ---------------------------------------------------------------------------

def emit_compositor_tree(ver: tuple[int, ...], scene_var: str) -> str:
    """Return an expression string for the compositor node tree."""
    if _is_5x(ver):
        return f"{scene_var}.compositing_node_group"
    return f"{scene_var}.node_tree"


# ---------------------------------------------------------------------------
# Engine IDs
# ---------------------------------------------------------------------------

def eevee_engine_id(ver: tuple[int, ...]) -> str:
    """Return the correct EEVEE engine identifier string."""
    if _is_5x(ver):
        return "BLENDER_EEVEE"
    return "BLENDER_EEVEE_NEXT"


# ---------------------------------------------------------------------------
# MCP server instructions
# ---------------------------------------------------------------------------

_BACKEND_INSTRUCTIONS = """
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
"""

_DEFAULT_VIEWPOINT = """
You are not editing a scene. You are authoring a machine that
produces scenes. Every node graph, driver, and expression you
create is part of a system with inputs, controls, and outputs —
closer to a reusable Houdini HDA than a saved file.

First instinct: derive. Compute values from scene signals — position,
normal, curvature, proximity, noise — rather than assigning constants.
Derived values can be swept and randomized; hand-set values are dead
ends. If a property can't be varied from code, it's invisible to a
parameter sweep.

Blender's procedural surface spans Geometry Nodes (structure), shader
nodes (appearance), compositor (passes/labels), and drivers (parametric
links) — connected through named attributes and render passes, one
machine, not separate tools.

Expose controls. Surface the parameters that matter and bury the
rest. The interface of your system is as important as its internals.

Verify across the parameter space. One seed, one frame, one camera
angle is never proof. Vary inputs and confirm the output stays
coherent under change.

Before building, read the relevant knowledge/*.md file for depth.

When the user asks for direct scene manipulation — specific placement,
specific values — do exactly that. This posture is a default, not a
cage.
"""

DEFAULT_VIEWPOINT = _DEFAULT_VIEWPOINT.strip()


def build_server_instructions(ver: tuple[int, ...], viewpoint: str = "") -> str:
    """Build the dynamic MCP server instructions string."""
    ver_str = ".".join(str(v) for v in ver)

    if _is_5x(ver):
        api_notes = (
            f"API mode: 5.x — use bracket access on modifier properties.inputs "
            f"(mod.properties.inputs[ident]['value']), "
            f"scene.compositing_node_group for compositor, "
            f"engine ID BLENDER_EEVEE for Eevee."
        )
    else:
        api_notes = (
            f"API mode: 4.x — use mod[ident] for modifier inputs, "
            f"scene.node_tree for compositor, "
            f"engine ID BLENDER_EEVEE_NEXT for Eevee."
        )

    parts = [
        f"Connected to Blender {ver_str}. {api_notes}",
        _BACKEND_INSTRUCTIONS.strip(),
    ]
    if viewpoint.strip():
        parts.append("## Viewpoint\n\n" + viewpoint.strip())
    return "\n\n".join(parts)
