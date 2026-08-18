"""SynthGen operators — F3/search-menu entry points for users.

Mirrors the MCP tools so users and agents share the same procedural workflow.
Container operators: create_container, add_asset, remove_asset.
Node Editor operators: auto_layout, tag_asset, save_asset.
"""

import os
import subprocess
import tempfile

import bpy

_addon_dir = os.path.dirname(os.path.abspath(__file__))
_real_addon = os.path.realpath(_addon_dir)
_repo_root = os.path.normpath(os.path.join(_real_addon, "..", ".."))
_assets_dir = os.path.join(_repo_root, "assets")

_INTERNAL_GROUPS = frozenset({"SynthGen.Container", "SynthGen"})

# Disk asset cache — populated in invoke(), read in enum callbacks.
_disk_assets = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_container(obj):
    """Return the container node-group name on *obj*, or None."""
    if obj is None:
        return None
    for mod in obj.modifiers:
        if (mod.type == "NODES"
                and mod.node_group
                and mod.node_group.get("synthgen_type") == "container"):
            return mod.node_group.name
    return None


def _discover_disk_assets():
    """Scan assets/ directory for SynthGen node groups. {name: filepath}."""
    result = {}
    if not os.path.isdir(_assets_dir):
        return result
    for f in sorted(os.listdir(_assets_dir)):
        if not f.endswith(".blend") or f.endswith(".autosave.blend"):
            continue
        filepath = os.path.join(_assets_dir, f)
        try:
            with bpy.data.libraries.load(filepath) as (data_from, _):
                for name in data_from.node_groups:
                    if name.startswith("SynthGen.") and name not in _INTERNAL_GROUPS:
                        result[name] = filepath
        except Exception:
            pass
    return result


def _load_node_group(name, filepath):
    """Load a specific node group from a .blend file."""
    with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
        data_to.node_groups = [ng for ng in data_from.node_groups if ng == name]
    return bpy.data.node_groups.get(name)


def _ensure_template():
    """Load SynthGen.Container template if not already present."""
    if bpy.data.node_groups.get("SynthGen.Container"):
        return
    filepath = os.path.join(_assets_dir, "container.blend")
    if os.path.isfile(filepath):
        with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
            data_to.node_groups = [
                ng for ng in data_from.node_groups if ng == "SynthGen.Container"
            ]


# ---------------------------------------------------------------------------
# Create Container
# ---------------------------------------------------------------------------

class SYNTHGEN_OT_create_container(bpy.types.Operator):
    bl_idname = "synthgen.create_container"
    bl_label = "Container"
    bl_description = "Create a new SynthGen procedural container"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _ensure_template()

        bpy.ops.object.empty_add(type='PLAIN_AXES', location=context.scene.cursor.location)
        obj = context.active_object
        obj.name = "SynthGen"

        from synthgen import containers

        result = containers.create(obj.name)
        self.report({'INFO'},
                    f"Container '{result['container']}' created")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Add Asset
# ---------------------------------------------------------------------------

def _get_available_assets(self, context):
    """Enum callback: SynthGen assets from loaded groups + disk cache."""
    items = []
    seen = set()

    for ng in bpy.data.node_groups:
        if ng.name.startswith("SynthGen.") and ng.name not in _INTERNAL_GROUPS:
            items.append((ng.name, ng.name.removeprefix("SynthGen."), ""))
            seen.add(ng.name)

    for name in _disk_assets:
        if name not in seen:
            items.append((name, name.removeprefix("SynthGen."),
                          "Will be imported from assets/"))
            seen.add(name)

    return items if items else [("NONE", "No assets found", "")]


class SYNTHGEN_OT_add_asset(bpy.types.Operator):
    bl_idname = "synthgen.add_asset"
    bl_label = "SynthGen: Add Asset"
    bl_description = "Add a SynthGen asset into the active object's container"
    bl_options = {'REGISTER', 'UNDO'}

    asset: bpy.props.EnumProperty(
        name="Asset",
        items=_get_available_assets,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and _find_container(context.active_object) is not None)

    def invoke(self, context, event):
        global _disk_assets
        _disk_assets = _discover_disk_assets()
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "asset")

    def execute(self, context):
        if self.asset == "NONE":
            self.report({'WARNING'}, "No asset selected")
            return {'CANCELLED'}

        container_name = _find_container(context.active_object)

        if not bpy.data.node_groups.get(self.asset):
            filepath = _disk_assets.get(self.asset)
            if not filepath:
                self.report({'ERROR'}, f"Asset '{self.asset}' not found")
                return {'CANCELLED'}
            _load_node_group(self.asset, filepath)

        from synthgen import containers

        result = containers.add_asset(container_name, self.asset)
        self.report({'INFO'}, f"Added '{result['asset']}'")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Remove Asset
# ---------------------------------------------------------------------------

def _get_container_assets(self, context):
    """Enum callback: assets currently in the active object's container."""
    container_name = _find_container(
        context.active_object if context.active_object else None)
    if not container_name:
        return [("NONE", "No container", "")]
    ng = bpy.data.node_groups.get(container_name)
    if not ng:
        return [("NONE", "Container not found", "")]
    items = []
    for node in ng.nodes:
        asset = node.get("synthgen_asset")
        if not asset and node.type == "GROUP" and node.node_tree:
            asset = node.node_tree.get("synthgen_asset")
        if asset:
            items.append((node.name, asset.removeprefix("SynthGen."), ""))
    return items if items else [("NONE", "No assets", "")]


class SYNTHGEN_OT_remove_asset(bpy.types.Operator):
    bl_idname = "synthgen.remove_asset"
    bl_label = "SynthGen: Remove Asset"
    bl_description = "Remove an asset from the active object's container"
    bl_options = {'REGISTER', 'UNDO'}

    asset_node: bpy.props.EnumProperty(
        name="Asset",
        items=_get_container_assets,
    )

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None
                and _find_container(context.active_object) is not None)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "asset_node")

    def execute(self, context):
        if self.asset_node == "NONE":
            self.report({'WARNING'}, "No asset selected")
            return {'CANCELLED'}

        container_name = _find_container(context.active_object)

        from synthgen import containers

        containers.remove_asset(container_name, self.asset_node)
        self.report({'INFO'}, f"Removed '{self.asset_node}'")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Auto Layout (Node Editor)
# ---------------------------------------------------------------------------

class SYNTHGEN_OT_auto_layout(bpy.types.Operator):
    bl_idname = "synthgen.auto_layout"
    bl_label = "Auto Layout"
    bl_description = "Arrange nodes using topological layering (selected only, or all)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.area
                and context.area.type == 'NODE_EDITOR'
                and context.space_data.edit_tree is not None)

    def execute(self, context):
        from synthgen.layout import auto_layout

        tree = context.space_data.edit_tree
        selected = [n for n in tree.nodes if n.select]
        if selected:
            auto_layout(tree, nodes=selected)
            self.report({'INFO'}, f"Laid out {len(selected)} selected nodes")
        else:
            auto_layout(tree)
            self.report({'INFO'}, f"Laid out {len(tree.nodes)} nodes")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Tag as Asset (Node Editor)
# ---------------------------------------------------------------------------

class SYNTHGEN_OT_tag_asset(bpy.types.Operator):
    bl_idname = "synthgen.tag_asset"
    bl_label = "Tag as Asset"
    bl_description = "Mark the active node group as a SynthGen asset"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not (context.area and context.area.type == 'NODE_EDITOR'):
            return False
        tree = context.space_data.edit_tree
        if tree is None:
            return False
        if not hasattr(tree, 'bl_idname') or tree.bl_idname != 'GeometryNodeTree':
            return False
        # Must be editing a node group, not the top-level modifier tree
        path = context.space_data.path
        return len(path) > 1

    def execute(self, context):
        tree = context.space_data.edit_tree
        if tree.get("synthgen_asset"):
            self.report({'INFO'}, f"'{tree.name}' is already tagged")
            return {'FINISHED'}

        if not tree.name.startswith("SynthGen."):
            tree.name = f"SynthGen.{tree.name}"

        tree["synthgen_asset"] = tree.name
        self.report({'INFO'}, f"Tagged '{tree.name}' as SynthGen asset")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Save Asset (Node Editor)
# ---------------------------------------------------------------------------

_BLENDER_EXE = os.environ.get(
    "SYNTHGEN_BLENDER_EXE",
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
)


class SYNTHGEN_OT_save_asset(bpy.types.Operator):
    bl_idname = "synthgen.save_asset"
    bl_label = "Save Asset"
    bl_description = "Export the tagged node group as a SynthGen asset"
    bl_options = {'REGISTER', 'UNDO'}

    asset_name: bpy.props.StringProperty(
        name="Name",
        description="Asset name (will be prefixed with 'SynthGen.' if missing)",
    )

    category: bpy.props.EnumProperty(
        name="Category",
        items=[
            ('Distribution', 'Distribution', ''),
            ('Instancing', 'Instancing', ''),
            ('Camera', 'Camera', ''),
            ('Deformation', 'Deformation', ''),
            ('Container', 'Container', ''),
            ('Utility', 'Utility', ''),
        ],
        default='Utility',
    )

    @classmethod
    def poll(cls, context):
        if not (context.area and context.area.type == 'NODE_EDITOR'):
            return False
        tree = context.space_data.edit_tree
        if tree is None:
            return False
        if not hasattr(tree, 'bl_idname') or tree.bl_idname != 'GeometryNodeTree':
            return False
        return bool(tree.get("synthgen_asset"))

    def invoke(self, context, event):
        tree = context.space_data.edit_tree
        self.asset_name = tree.name
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "asset_name")
        layout.prop(self, "category")

    def execute(self, context):
        from synthgen.assets import (
            validate, slug_from_name, ensure_catalog_entry, generate_manifest,
            CATEGORY_CATALOG,
        )

        tree = context.space_data.edit_tree

        # Apply user's chosen name
        name = self.asset_name.strip()
        if not name:
            self.report({'ERROR'}, "Asset name cannot be empty")
            return {'CANCELLED'}
        if not name.startswith("SynthGen."):
            name = f"SynthGen.{name}"
        if tree.name != name:
            tree.name = name
            tree["synthgen_asset"] = name

        result = validate(tree)
        for w in result.warnings:
            self.report({'WARNING'}, w)
        if not result.ok:
            for e in result.errors:
                self.report({'ERROR'}, e)
            return {'CANCELLED'}

        # Save a temp copy so the subprocess can read current state
        # (works even if the user hasn't saved the file yet)
        tmp_blend = os.path.join(tempfile.gettempdir(), "_synthgen_export_src.blend")
        bpy.ops.wm.save_as_mainfile(filepath=tmp_blend, copy=True)

        slug = slug_from_name(name)
        blend_out = os.path.join(_assets_dir, f"{slug}.blend")
        md_out = os.path.join(_assets_dir, f"{slug}.md")
        catalog_path = os.path.join(_assets_dir, "blender_assets.cats.txt")

        cat_uuid = ensure_catalog_entry(catalog_path, self.category)

        worker = os.path.join(_repo_root, "scripts", "_export_asset_worker.py")
        cmd = [
            _BLENDER_EXE, "-b", tmp_blend,
            "-P", worker, "--",
            "--tree", tree.name,
            "--output", blend_out,
            "--catalog-id", cat_uuid,
            "--description", tree.get("synthgen_description", ""),
            "--category", self.category,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
            )
            if proc.returncode != 0:
                self.report({'ERROR'}, f"Export failed: {proc.stderr[-500:]}")
                return {'CANCELLED'}
        except FileNotFoundError:
            self.report({'ERROR'},
                        f"Blender not found at '{_BLENDER_EXE}'. "
                        "Set SYNTHGEN_BLENDER_EXE env var.")
            return {'CANCELLED'}
        except subprocess.TimeoutExpired:
            self.report({'ERROR'}, "Export timed out after 60s")
            return {'CANCELLED'}
        finally:
            try:
                os.remove(tmp_blend)
            except OSError:
                pass

        if not os.path.isfile(md_out):
            manifest = generate_manifest(tree, self.category)
            with open(md_out, "w", newline="\n") as f:
                f.write(manifest)
            self.report({'INFO'}, f"Generated manifest: {os.path.basename(md_out)}")
        else:
            self.report({'INFO'}, f"Manifest exists, not overwritten: {os.path.basename(md_out)}")

        self.report({'INFO'}, f"Asset saved: {os.path.basename(blend_out)}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Add menu (Shift+A) submenu
# ---------------------------------------------------------------------------

class SYNTHGEN_MT_add_menu(bpy.types.Menu):
    bl_idname = "SYNTHGEN_MT_add_menu"
    bl_label = "SynthGen"

    def draw(self, context):
        layout = self.layout
        layout.operator("synthgen.create_container", icon='OUTLINER_OB_EMPTY')
        layout.separator()
        layout.operator("synthgen.add_asset", icon='ADD')
        layout.operator("synthgen.remove_asset", icon='REMOVE')


def _draw_add_menu(self, context):
    self.layout.separator()
    self.layout.menu("SYNTHGEN_MT_add_menu", icon='GEOMETRY_NODES')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = [
    SYNTHGEN_OT_create_container,
    SYNTHGEN_OT_add_asset,
    SYNTHGEN_OT_remove_asset,
    SYNTHGEN_OT_auto_layout,
    SYNTHGEN_OT_tag_asset,
    SYNTHGEN_OT_save_asset,
    SYNTHGEN_MT_add_menu,
]

_keymaps = []


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_add.append(_draw_add_menu)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Node Editor", space_type='NODE_EDITOR')
        kmi = km.keymap_items.new("synthgen.auto_layout", 'L', 'PRESS')
        _keymaps.append((km, kmi))


def unregister():
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    bpy.types.VIEW3D_MT_add.remove(_draw_add_menu)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
