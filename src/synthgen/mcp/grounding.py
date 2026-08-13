"""Grounding enforcement — validate node/socket/setting identifiers against schema.

Hallucinated identifiers are rejected at the MCP boundary before reaching bpy.
Near-misses get "did you mean?" suggestions via fuzzy matching.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from synthgen.schema.query import load_schema


@dataclass
class ValidationResult:
    valid: bool
    canonical: str | None = None
    suggestions: list[str] = field(default_factory=list)
    message: str = ""


def _load_nodes(tree_type: str, blender_dir: str | None = None) -> dict:
    schema, _ = load_schema(tree_type, blender_dir=blender_dir)
    return schema["nodes"]


def _suggest(target: str, candidates: list[str], n: int = 5) -> list[str]:
    return difflib.get_close_matches(target, candidates, n=n, cutoff=0.5)


def validate_node_type(
    node_type: str, tree_type: str, blender_dir: str | None = None,
) -> ValidationResult:
    """Check whether a node_type is a valid Blender node identifier."""
    nodes = _load_nodes(tree_type, blender_dir)

    if node_type in nodes:
        return ValidationResult(valid=True, canonical=node_type)

    all_ids = list(nodes.keys())
    suggestions = _suggest(node_type, all_ids)

    if suggestions:
        hint = ", ".join(f'"{s}"' for s in suggestions)
        return ValidationResult(
            valid=False,
            suggestions=suggestions,
            message=f'Unknown node type "{node_type}" in {tree_type} schema. Did you mean: {hint}?',
        )

    return ValidationResult(
        valid=False,
        message=f'Unknown node type "{node_type}" in {tree_type} schema. '
                f"Use schema_find to search for valid node types.",
    )


def validate_socket(
    node_type: str,
    socket_id: str,
    tree_type: str,
    is_input: bool = True,
    blender_dir: str | None = None,
) -> ValidationResult:
    """Check whether a socket identifier exists on a given node type."""
    nodes = _load_nodes(tree_type, blender_dir)

    if node_type not in nodes:
        return ValidationResult(
            valid=False,
            message=f'Cannot validate socket — node type "{node_type}" not found in {tree_type} schema.',
        )

    node = nodes[node_type]
    direction = "inputs" if is_input else "outputs"
    sockets = node[direction]
    socket_ids = [s["identifier"] for s in sockets]

    if socket_id in socket_ids:
        return ValidationResult(valid=True, canonical=socket_id)

    # Check if they used the label instead of the identifier
    for s in sockets:
        if s["name"] == socket_id and s["identifier"] != socket_id:
            return ValidationResult(
                valid=False,
                canonical=s["identifier"],
                suggestions=[s["identifier"]],
                message=(
                    f'"{socket_id}" is the display label, not the socket identifier. '
                    f'Use "{s["identifier"]}" instead.'
                ),
            )

    suggestions = _suggest(socket_id, socket_ids)
    if suggestions:
        hint = ", ".join(f'"{s}"' for s in suggestions)
        return ValidationResult(
            valid=False,
            suggestions=suggestions,
            message=f'Unknown {direction[:-1]} socket "{socket_id}" on {node_type}. Did you mean: {hint}?',
        )

    available = ", ".join(f'"{s}"' for s in socket_ids)
    return ValidationResult(
        valid=False,
        message=f'Unknown {direction[:-1]} socket "{socket_id}" on {node_type}. '
                f"Available: {available}.",
    )


def validate_setting(
    node_type: str,
    setting_name: str,
    tree_type: str,
    blender_dir: str | None = None,
) -> ValidationResult:
    """Check whether a setting name exists on a given node type."""
    nodes = _load_nodes(tree_type, blender_dir)

    if node_type not in nodes:
        return ValidationResult(
            valid=False,
            message=f'Cannot validate setting — node type "{node_type}" not found in {tree_type} schema.',
        )

    node = nodes[node_type]
    setting_names = [s["name"] for s in node["settings"]]

    if setting_name in setting_names:
        return ValidationResult(valid=True, canonical=setting_name)

    suggestions = _suggest(setting_name, setting_names)
    if suggestions:
        hint = ", ".join(f'"{s}"' for s in suggestions)
        return ValidationResult(
            valid=False,
            suggestions=suggestions,
            message=f'Unknown setting "{setting_name}" on {node_type}. Did you mean: {hint}?',
        )

    if setting_names:
        available = ", ".join(f'"{s}"' for s in setting_names)
        return ValidationResult(
            valid=False,
            message=f'Unknown setting "{setting_name}" on {node_type}. '
                    f"Available settings: {available}.",
        )

    return ValidationResult(
        valid=False,
        message=f'Node type "{node_type}" has no enum settings.',
    )
