"""SynthGen asset export — validation, manifest generation, catalog wiring.

Shared by the Blender operator and the MCP ``save_asset`` tool.  All functions
that touch ``bpy`` are guarded so the module stays importable offline for
testing.
"""

from __future__ import annotations

import os
import re
import uuid

SYNTHGEN_NS = uuid.UUID("e18a1b41-afdb-4720-9301-068347e18f12")

CATEGORY_CATALOG = {
    "Distribution": ("21442b1d-30de-4288-a6f7-52d3d19b71a6", "SynthGen/Distribution"),
    "Instancing":   ("106165cc-64d3-4148-8901-c3de44bab598", "SynthGen/Instancing"),
    "Camera":       ("a5f7c3d2-8e19-4b6a-9c01-7d3f52a89e14", "SynthGen/Camera"),
    "Deformation":  ("b3d94e57-6a21-4f38-b5c2-9e84d12f7a63", "SynthGen/Deformation"),
    "Container":    ("1827f2ea-4a12-43f3-afa3-bd76819313d6", "SynthGen/Container"),
    "Utility":      ("e18a1b41-afdb-4720-9301-068347e18f12", "SynthGen"),
}

_SOCKET_TYPE_NAMES = {
    "NodeSocketFloat": "Float",
    "NodeSocketInt": "Int",
    "NodeSocketBool": "Bool",
    "NodeSocketVector": "Vector",
    "NodeSocketColor": "Color",
    "NodeSocketString": "String",
    "NodeSocketGeometry": "Geometry",
    "NodeSocketObject": "Object",
    "NodeSocketCollection": "Collection",
    "NodeSocketImage": "Image",
    "NodeSocketMaterial": "Material",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationResult:
    __slots__ = ("errors", "warnings")

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.errors

    def __repr__(self):
        return f"ValidationResult(errors={self.errors}, warnings={self.warnings})"


def validate(tree) -> ValidationResult:
    """Validate a node tree for SynthGen asset export.

    Parameters
    ----------
    tree : bpy.types.NodeTree
        The node group to validate.

    Returns
    -------
    ValidationResult
        ``.ok`` is False if any blocking error was found.
    """
    result = ValidationResult()

    if not tree.get("synthgen_asset"):
        result.errors.append("Node group is not tagged as a SynthGen asset. Use 'Tag as Asset' first.")

    has_inputs = any(
        item.in_out == "INPUT"
        for item in tree.interface.items_tree
        if hasattr(item, "in_out")
    )
    has_outputs = any(
        item.in_out == "OUTPUT"
        for item in tree.interface.items_tree
        if hasattr(item, "in_out")
    )
    if not has_inputs and not has_outputs:
        result.errors.append("Node group has no interface sockets.")

    if not tree.name.startswith("SynthGen."):
        result.warnings.append(f"Name '{tree.name}' missing 'SynthGen.' prefix.")

    for node in tree.nodes:
        if node.bl_idname == "GeometryNodeViewer":
            result.warnings.append(f"Viewer node '{node.name}' will be stripped from export.")

    return result


# ---------------------------------------------------------------------------
# Slug / naming
# ---------------------------------------------------------------------------

def slug_from_name(name: str) -> str:
    """Convert a SynthGen asset name to a filesystem slug.

    ``SynthGen.Scatter on Surface`` → ``scatter_on_surface``
    """
    bare = name.removeprefix("SynthGen.").strip()
    return re.sub(r"[^a-z0-9]+", "_", bare.lower()).strip("_")


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def catalog_uuid(name: str) -> str:
    """Deterministic UUID for a SynthGen asset catalog entry."""
    return str(uuid.uuid5(SYNTHGEN_NS, name))


def ensure_catalog_entry(catalog_path: str, category: str) -> str:
    """Ensure the catalog file has an entry for *category*.  Idempotent.

    Returns the catalog UUID for the category.
    """
    cat_uuid, cat_path = CATEGORY_CATALOG.get(category, (None, None))
    if cat_uuid is None:
        cat_uuid = catalog_uuid(category)
        cat_path = f"SynthGen/{category}"

    if os.path.isfile(catalog_path):
        with open(catalog_path, "r") as f:
            content = f.read()
        if cat_uuid in content:
            return cat_uuid
    else:
        content = "VERSION 1\n\n"

    entry = f"{cat_uuid}:{cat_path}:SynthGen-{category}\n"
    with open(catalog_path, "w", newline="\n") as f:
        f.write(content.rstrip("\n") + "\n" + entry)

    return cat_uuid


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def _socket_type_name(socket_type: str) -> str:
    return _SOCKET_TYPE_NAMES.get(socket_type, socket_type)


def _format_default(item) -> str:
    """Best-effort string representation of a socket default value."""
    try:
        val = item.default_value
        if val is None:
            return "—"
        if isinstance(val, str):
            return f'"{val}"' if val else '""'
        if isinstance(val, bool):
            return str(val).lower()
        if isinstance(val, float):
            return f"{val:g}"
        if isinstance(val, int):
            return str(val)
        return str(val)
    except (AttributeError, TypeError):
        return "—"


def generate_manifest(tree, category: str, version: str = "0.1") -> str:
    """Generate a Markdown manifest for a node group.

    Parameters
    ----------
    tree : bpy.types.NodeTree
        The node group to document.
    category : str
        Asset category (e.g. "Distribution").
    version : str
        Asset version string.

    Returns
    -------
    str
        Markdown content ready to write to ``assets/<slug>.md``.
    """
    slug = slug_from_name(tree.name)
    display = tree.name.removeprefix("SynthGen.").strip()
    cat_path = CATEGORY_CATALOG.get(category, (None, f"SynthGen/{category}"))[1]

    lines = [
        "---",
        f"asset: {tree.name}",
        f"file: {slug}.blend",
        f"node_group: {tree.name}",
        f"category: {category.lower()}",
        f"catalog_path: {cat_path}",
        f"version: {version}",
        f'blender: "5.2"',
        "---",
        "",
        f"# {display}",
        "",
        "<!-- Description -->",
        "",
        "## Parameters",
        "",
        "| Name | Identifier | Type | Default | Purpose |",
        "|------|-----------|------|---------|---------|",
    ]

    for item in tree.interface.items_tree:
        if not hasattr(item, "in_out"):
            continue
        type_name = _socket_type_name(item.socket_type)
        default = _format_default(item)
        lines.append(
            f"| {item.name} | {item.identifier} | {type_name} | {default} | |"
        )

    lines.extend([
        "",
        "## Composes with",
        "",
        "<!-- Upstream/downstream assets -->",
        "",
        "## Limitations",
        "",
        "<!-- Known constraints -->",
        "",
    ])

    return "\n".join(lines)
