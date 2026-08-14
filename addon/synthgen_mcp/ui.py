"""N-panel UI for Synthgen MCP — server status, start/stop, config copy."""

import bpy

from . import server as srv


class SYNTHGEN_OT_start_server(bpy.types.Operator):
    bl_idname = "synthgen.start_server"
    bl_label = "Start Server"
    bl_description = "Start the SSE MCP server"

    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        port = prefs.preferences.port if prefs else 8400
        addon_dir = __import__("os").path.dirname(
            __import__("os").path.abspath(__file__)
        )
        try:
            srv.start(port, addon_dir)
            self.report({"INFO"}, f"MCP server started on port {port}")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
        return {"FINISHED"}


class SYNTHGEN_OT_stop_server(bpy.types.Operator):
    bl_idname = "synthgen.stop_server"
    bl_label = "Stop Server"
    bl_description = "Stop the SSE MCP server"

    def execute(self, context):
        srv.stop()
        self.report({"INFO"}, "MCP server stopped")
        return {"FINISHED"}


class SYNTHGEN_OT_copy_config(bpy.types.Operator):
    bl_idname = "synthgen.copy_config"
    bl_label = "Copy MCP Config"
    bl_description = "Copy the MCP client configuration JSON to clipboard"

    def execute(self, context):
        port = srv.get_port()
        config = f'{{"synthgen": {{"url": "http://localhost:{port}/sse"}}}}'
        context.window_manager.clipboard = config
        self.report({"INFO"}, "MCP config copied to clipboard")
        return {"FINISHED"}


class SYNTHGEN_PT_mcp_panel(bpy.types.Panel):
    bl_label = "Synthgen MCP"
    bl_idname = "SYNTHGEN_PT_mcp_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Synthgen MCP"

    def draw(self, context):
        layout = self.layout
        running = srv.is_running()
        port = srv.get_port()

        box = layout.box()
        row = box.row()
        if running:
            row.label(text=f"Server running on port {port}", icon="CHECKMARK")
        else:
            row.label(text="Server stopped", icon="X")

        row = layout.row(align=True)
        if running:
            row.operator("synthgen.stop_server", icon="PAUSE")
        else:
            row.operator("synthgen.start_server", icon="PLAY")

        layout.separator()
        layout.operator("synthgen.copy_config", icon="COPYDOWN")

        if running:
            box = layout.box()
            box.label(text="Connect from your IDE:", icon="INFO")
            box.label(text=f"  URL: http://localhost:{port}/sse")


_classes = [
    SYNTHGEN_OT_start_server,
    SYNTHGEN_OT_stop_server,
    SYNTHGEN_OT_copy_config,
    SYNTHGEN_PT_mcp_panel,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
