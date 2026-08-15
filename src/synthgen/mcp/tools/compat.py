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

def build_server_instructions(ver: tuple[int, ...]) -> str:
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

    return (
        f"Connected to Blender {ver_str}. {api_notes}\n\n"
        "Grounded Blender tools for procedural 3D synthetic data. "
        "Schema-validated node/socket identifiers, scene-graph introspection, "
        "and procedural authoring — never hallucinates Blender API names."
    )
