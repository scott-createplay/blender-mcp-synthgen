"""
dump_node_schema.py — node-schema extractor for Blender.  (v4-tritree)

Run inside Blender (Scripting tab -> paste -> Run). Writes THREE JSON files to your
home dir, describing every node usable in each tree, with stable socket
`identifier`s (used for Python linking) and the enum "settings" that steer a node:

  <home>/blender_gn_schema.json          — Geometry Nodes tree
  <home>/blender_shader_schema.json      — Shader (material) node tree
  <home>/blender_compositor_schema.json  — Compositor node tree

Why three: a synthetic-data pipeline spans all three — geometry nodes for procedural
structure/instancing, shader nodes for per-instance material variation, compositor for
render-pass → ground-truth outputs (masks/depth/normal) and image-space randomization.
Geometry and shading are bridged by named attributes (GN Store Named Attribute <->
shader Attribute node); shading and compositor are bridged by render passes / AOVs.
"""

import bpy
import json
import os
import traceback


def collect_candidate_idnames():
    """All registered node-type names in bpy.types (superset; validity tested per-tree)."""
    node_base = bpy.types.Node
    names = []
    for name in dir(bpy.types):
        try:
            cls = getattr(bpy.types, name)
        except Exception:
            continue
        if isinstance(cls, type) and issubclass(cls, node_base) and cls is not node_base:
            names.append(name)
    return sorted(set(names))


def base_node_prop_ids():
    return {p.identifier for p in bpy.types.Node.bl_rna.properties}


def describe_sockets(sockets):
    return [{"name": s.name, "identifier": s.identifier, "type": s.type} for s in sockets]


def describe_settings(node, base_ids):
    settings = []
    for p in node.bl_rna.properties:
        if p.identifier in base_ids or p.is_readonly or p.type != "ENUM":
            continue
        try:
            values = [e.identifier for e in p.enum_items]
        except Exception:
            values = []
        if not values:
            continue
        default = getattr(node, p.identifier, None)
        if isinstance(default, set):   # ENUM_FLAG (multi-select) -> set
            default = sorted(default)
        settings.append({"name": p.identifier, "default": default, "values": values})
    return settings


def make_host(tree_type):
    """Return (node_tree, cleanup_callable) for the requested tree type.

    Shader nodes are introspected in a real material tree so BSDFs / Output Material
    are captured. Geometry and Compositor use a node group of the matching type.
    """
    if tree_type == "ShaderNodeTree":
        mat = bpy.data.materials.new("__introspect_mat__")
        mat.use_nodes = True
        return mat.node_tree, lambda: bpy.data.materials.remove(mat)
    # Compositor (5.x): the scene compositor is now a node-group datablock
    # (scene.use_nodes / scene.node_tree were removed), so a plain node group of
    # type CompositorNodeTree is the correct host. A few scene-only I/O nodes
    # (Render Layers / Composite) may land in `skipped`; captured specially if needed.
    ng = bpy.data.node_groups.new("__introspect__", tree_type)
    return ng, lambda: bpy.data.node_groups.remove(ng)


def extract(tree_type, relevant_prefixes, idnames, base_ids):
    tree, cleanup = make_host(tree_type)
    nodes_out, skipped = {}, {}
    for idn in idnames:
        try:
            node = tree.nodes.new(idn)
        except Exception as exc:
            if idn.startswith(relevant_prefixes):
                skipped[idn] = str(exc).splitlines()[0] if str(exc) else "could not instantiate"
            continue
        try:
            nodes_out[idn] = {
                "label": getattr(node, "bl_label", "") or idn,
                "inputs": describe_sockets(node.inputs),
                "outputs": describe_sockets(node.outputs),
                "settings": describe_settings(node, base_ids),
            }
        except Exception:
            skipped[idn] = "read error: " + traceback.format_exc().splitlines()[-1]
        finally:
            try:
                tree.nodes.remove(node)
            except Exception:
                pass
    cleanup()
    return nodes_out, skipped


# (tree_type, output filename, prefixes we care about flagging when they fail)
TREES = [
    ("GeometryNodeTree", "blender_gn_schema.json", ("GeometryNode", "FunctionNode", "ShaderNode")),
    ("ShaderNodeTree", "blender_shader_schema.json", ("ShaderNode", "FunctionNode")),
    ("CompositorNodeTree", "blender_compositor_schema.json", ("CompositorNode",)),
]


def main():
    base_ids = base_node_prop_ids()
    idnames = collect_candidate_idnames()

    print("=" * 64)
    for tree_type, fname, prefixes in TREES:
        nodes_out, skipped = extract(tree_type, prefixes, idnames, base_ids)
        schema = {
            "extractor_version": "v4-tritree",
            "tree_type": tree_type,
            "blender_version": bpy.app.version_string,
            "blender_version_tuple": list(bpy.app.version),
            "node_count": len(nodes_out),
            "skipped_count": len(skipped),
            "nodes": nodes_out,
            "skipped": skipped,
        }
        out_path = os.path.join(os.path.expanduser("~"), fname)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
        print(f"[v4] {tree_type:18} {len(nodes_out):4} nodes  ({len(skipped)} skipped)  -> {out_path}")
    print("=" * 64)


main()
