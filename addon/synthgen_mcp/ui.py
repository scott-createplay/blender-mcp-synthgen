"""N-panel UI for Synthgen MCP — server status, start/stop, config copy, watchdog."""

import json
import logging
import os

import bpy

from . import server as srv

logger = logging.getLogger(__name__)

_WATCHDOG_INTERVAL = 5.0
_watchdog_was_running = False


_IDE_CONFIGS = {
    "CLAUDE": {
        "label": "Claude Code",
        "path": os.path.join(os.path.expanduser("~"), ".claude", "settings.json"),
        "key": "mcpServers",
    },
    "CURSOR": {
        "label": "Cursor",
        "path": os.path.join(os.path.expanduser("~"), ".cursor", "mcp.json"),
        "key": "mcpServers",
    },
}


def _watchdog_poll() -> float | None:
    """Detect if the server thread died and surface the error."""
    global _watchdog_was_running
    running = srv.is_running()
    if _watchdog_was_running and not running:
        error = srv.get_last_error()
        msg = f"MCP server thread died: {error}" if error else "MCP server thread died unexpectedly"
        logger.error(msg)
        _watchdog_was_running = False
        for area in bpy.context.screen.areas if bpy.context.screen else []:
            if area.type == "VIEW_3D":
                area.tag_redraw()
        return None
    _watchdog_was_running = running
    return _WATCHDOG_INTERVAL if running else None


def start_watchdog() -> None:
    """Start the watchdog timer (call after server starts)."""
    global _watchdog_was_running
    _watchdog_was_running = True
    if not bpy.app.timers.is_registered(_watchdog_poll):
        bpy.app.timers.register(_watchdog_poll, first_interval=_WATCHDOG_INTERVAL)


def stop_watchdog() -> None:
    """Stop the watchdog timer."""
    global _watchdog_was_running
    _watchdog_was_running = False
    if bpy.app.timers.is_registered(_watchdog_poll):
        bpy.app.timers.unregister(_watchdog_poll)


def _format_uptime(seconds: float) -> str:
    """Format seconds into a human-readable uptime string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


class SYNTHGEN_OT_start_server(bpy.types.Operator):
    bl_idname = "synthgen.start_server"
    bl_label = "Start Server"
    bl_description = "Start the SSE MCP server"

    def execute(self, context):
        prefs = context.preferences.addons.get(__package__)
        port = prefs.preferences.port if prefs else 8400
        addon_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            srv.start(port, addon_dir)
            start_watchdog()
            self.report({"INFO"}, f"MCP server started on port {port}")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
        return {"FINISHED"}


class SYNTHGEN_OT_stop_server(bpy.types.Operator):
    bl_idname = "synthgen.stop_server"
    bl_label = "Stop Server"
    bl_description = "Stop the SSE MCP server"

    def execute(self, context):
        stop_watchdog()
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


class SYNTHGEN_OT_connect_ide(bpy.types.Operator):
    bl_idname = "synthgen.connect_ide"
    bl_label = "Connect IDE"
    bl_description = "Write the MCP server entry into your IDE's config file"

    ide: bpy.props.EnumProperty(
        name="IDE",
        items=[
            ("CLAUDE", "Claude Code", "Write to ~/.claude/settings.json"),
            ("CURSOR", "Cursor", "Write to ~/.cursor/mcp.json"),
        ],
        default="CLAUDE",
    )

    def execute(self, context):
        port = srv.get_port()
        cfg = _IDE_CONFIGS[self.ide]
        config_path = cfg["path"]
        entry = {"url": f"http://localhost:{port}/sse"}

        try:
            if os.path.isfile(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                os.makedirs(os.path.dirname(config_path), exist_ok=True)
                data = {}

            servers = data.setdefault(cfg["key"], {})
            servers["synthgen"] = entry

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            self.report({"INFO"},
                        f"Synthgen MCP added to {cfg['label']} config")
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to write config: {exc}")
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        self.layout.prop(self, "ide")


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
        error = srv.get_last_error()

        box = layout.box()
        row = box.row()
        if running:
            row.label(text=f"Server running on port {port}", icon="CHECKMARK")
            uptime = srv.get_uptime()
            tools = srv.get_tool_count()
            col = box.column(align=True)
            if uptime is not None:
                col.label(text=f"Uptime: {_format_uptime(uptime)}")
            if tools > 0:
                col.label(text=f"Tools: {tools}")
        elif error:
            row.label(text="Server crashed", icon="ERROR")
            box.label(text=error)
        else:
            row.label(text="Server stopped", icon="X")

        row = layout.row(align=True)
        if running:
            row.operator("synthgen.stop_server", icon="PAUSE")
        else:
            row.operator("synthgen.start_server", icon="PLAY")

        layout.separator()
        row = layout.row(align=True)
        row.operator("synthgen.connect_ide", icon="LINKED")
        row.operator("synthgen.copy_config", icon="COPYDOWN")

        if running:
            box = layout.box()
            box.label(text="Connect from your IDE:", icon="INFO")
            box.label(text=f"  URL: http://localhost:{port}/sse")
            box.label(text=f"  Health: http://localhost:{port}/health")


_classes = [
    SYNTHGEN_OT_start_server,
    SYNTHGEN_OT_stop_server,
    SYNTHGEN_OT_copy_config,
    SYNTHGEN_OT_connect_ide,
    SYNTHGEN_PT_mcp_panel,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
