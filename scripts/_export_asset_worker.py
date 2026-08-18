"""Headless Blender worker — export a single node group as an isolated .blend.

Usage (called by the save-asset operator, not directly):
    blender -b <source.blend> -P scripts/_export_asset_worker.py -- \
        --tree "SynthGen.Scatter on Surface" \
        --output "assets/scatter_on_surface.blend" \
        --catalog-id "21442b1d-30de-4288-a6f7-52d3d19b71a6" \
        --description "Short description" \
        --category "Distribution"

The script:
1. Opens the source .blend (via -b flag)
2. Finds the target node group
3. Strips Viewer nodes from the group
4. Marks it as a Blender asset with metadata
5. Purges all unrelated data
6. Saves to the output path
"""

import argparse
import sys

import bpy


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--catalog-id", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--category", default="Utility")
    return parser.parse_args(argv)


def main():
    args = _parse_args()

    tree = bpy.data.node_groups.get(args.tree)
    if tree is None:
        print(f"ERROR: node group '{args.tree}' not found")
        sys.exit(1)

    viewers = [n for n in tree.nodes if n.bl_idname == "GeometryNodeViewer"]
    for v in viewers:
        tree.nodes.remove(v)
        print(f"[export] Stripped Viewer node: {v.name}")

    keep_groups = set()
    def _collect_subgroups(ng):
        for node in ng.nodes:
            if node.type == "GROUP" and node.node_tree:
                if node.node_tree.name not in keep_groups:
                    keep_groups.add(node.node_tree.name)
                    _collect_subgroups(node.node_tree)
    keep_groups.add(tree.name)
    _collect_subgroups(tree)

    for ng in list(bpy.data.node_groups):
        if ng.name not in keep_groups:
            bpy.data.node_groups.remove(ng)

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)
    for cam in list(bpy.data.cameras):
        bpy.data.cameras.remove(cam, do_unlink=True)
    for light in list(bpy.data.lights):
        bpy.data.lights.remove(light, do_unlink=True)
    for col in list(bpy.data.collections):
        bpy.data.collections.remove(col)
    for img in list(bpy.data.images):
        bpy.data.images.remove(img)

    bpy.ops.outliner.orphans_purge(do_recursive=True)

    tree["synthgen_asset"] = tree.name
    tree.asset_mark()
    ad = tree.asset_data
    ad.description = args.description
    ad.author = "SynthGen"
    ad.catalog_id = args.catalog_id

    tags = [args.category.lower()]
    slug_parts = tree.name.removeprefix("SynthGen.").lower().split()
    tags.extend(slug_parts)
    for tag in tags:
        ad.tags.new(tag)

    bpy.ops.wm.save_as_mainfile(filepath=args.output)
    print(f"[export] Saved: {args.output}")
    print(f"[export] Node groups: {[ng.name for ng in bpy.data.node_groups]}")


if __name__ == "__main__":
    main()
