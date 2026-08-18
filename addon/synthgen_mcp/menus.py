"""SynthGen Node Editor menus — header menu + context menu entries."""

import bpy


# ---------------------------------------------------------------------------
# Submenus
# ---------------------------------------------------------------------------

class NODE_MT_synthgen_asset(bpy.types.Menu):
    bl_idname = "NODE_MT_synthgen_asset"
    bl_label = "Asset"

    def draw(self, _context):
        layout = self.layout
        layout.operator("synthgen.tag_asset", icon='BOOKMARKS')
        layout.operator("synthgen.save_asset", icon='FILE_TICK')


class NODE_MT_synthgen_layout(bpy.types.Menu):
    bl_idname = "NODE_MT_synthgen_layout"
    bl_label = "Layout"

    def draw(self, _context):
        layout = self.layout
        layout.operator("synthgen.auto_layout", icon='NODETREE')


# ---------------------------------------------------------------------------
# Top-level header menu
# ---------------------------------------------------------------------------

class NODE_MT_synthgen(bpy.types.Menu):
    bl_idname = "NODE_MT_synthgen"
    bl_label = "SynthGen"

    def draw(self, _context):
        layout = self.layout
        layout.menu("NODE_MT_synthgen_asset", icon='ASSET_MANAGER')
        layout.menu("NODE_MT_synthgen_layout", icon='GRAPH')


def _draw_header_menu(self, _context):
    self.layout.menu("NODE_MT_synthgen")


# ---------------------------------------------------------------------------
# Context menu (right-click) entries
# ---------------------------------------------------------------------------

def _draw_context_menu(self, _context):
    self.layout.separator()
    self.layout.operator("synthgen.auto_layout", icon='NODETREE')
    self.layout.operator("synthgen.tag_asset", icon='BOOKMARKS')
    self.layout.operator("synthgen.save_asset", icon='FILE_TICK')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = [
    NODE_MT_synthgen_asset,
    NODE_MT_synthgen_layout,
    NODE_MT_synthgen,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.NODE_MT_editor_menus.append(_draw_header_menu)
    bpy.types.NODE_MT_context_menu.append(_draw_context_menu)


def unregister():
    bpy.types.NODE_MT_context_menu.remove(_draw_context_menu)
    bpy.types.NODE_MT_editor_menus.remove(_draw_header_menu)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
