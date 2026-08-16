"""Synthgen MCP — self-contained Blender addon for procedural 3D synthetic data.

Bundles the synthgen MCP server as an SSE endpoint inside Blender.
Claude Code / Cursor / any MCP client connects via http://localhost:<port>/sse.
"""

import logging
import os
import sys

import bpy

logger = logging.getLogger(__name__)

bl_info = {
    "name": "Synthgen MCP",
    "author": "synthgen",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Synthgen MCP",
    "description": "Procedural 3D synthetic data tools via MCP (SSE server)",
    "category": "Development",
}

_addon_dir = os.path.dirname(os.path.abspath(__file__))

# Keep in sync with `synthgen.mcp.tools.compat.DEFAULT_VIEWPOINT` — the
# addon's bpy.props.StringProperty default must be a string literal at
# class-definition time, so this is a copy of the canonical text in
# compat.py. A test asserts the two stay in sync.
_DEFAULT_VIEWPOINT = (
    "You are not editing a scene. You are authoring a machine that\n"
    "produces scenes. Every node graph, driver, and expression you\n"
    "create is part of a system with inputs, controls, and outputs —\n"
    "closer to a reusable Houdini HDA than a saved file.\n"
    "\n"
    "First instinct: derive. Compute values from scene signals — position,\n"
    "normal, curvature, proximity, noise — rather than assigning constants.\n"
    "Derived values can be swept and randomized; hand-set values are dead\n"
    "ends. If a property can't be varied from code, it's invisible to a\n"
    "parameter sweep.\n"
    "\n"
    "Blender's procedural surface spans Geometry Nodes (structure), shader\n"
    "nodes (appearance), compositor (passes/labels), and drivers (parametric\n"
    "links) — connected through named attributes and render passes, one\n"
    "machine, not separate tools.\n"
    "\n"
    "Expose controls. Surface the parameters that matter and bury the\n"
    "rest. The interface of your system is as important as its internals.\n"
    "\n"
    "Verify across the parameter space. One seed, one frame, one camera\n"
    "angle is never proof. Vary inputs and confirm the output stays\n"
    "coherent under change.\n"
    "\n"
    "Before building, read the relevant knowledge/*.md file for depth.\n"
    "\n"
    "When the user asks for direct scene manipulation — specific placement,\n"
    "specific values — do exactly that. This posture is a default, not a\n"
    "cage."
)


def _setup_vendor(vendor: str) -> None:
    """Add vendor/ and its pywin32 subdirs to sys.path + DLL search path."""
    if not os.path.isdir(vendor):
        return
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    if sys.platform == "win32":
        for subdir in ("pywin32_system32", "win32", "win32\\lib"):
            p = os.path.join(vendor, subdir)
            if os.path.isdir(p):
                if p not in sys.path:
                    sys.path.insert(0, p)
                if subdir == "pywin32_system32":
                    try:
                        os.add_dll_directory(p)
                    except (OSError, AttributeError):
                        pass


def _setup_paths():
    """Add synthgen package and vendor deps to sys.path."""
    vendor = os.path.join(_addon_dir, "vendor")
    bundled_synthgen = os.path.join(_addon_dir, "synthgen")

    _setup_vendor(vendor)

    if os.path.isdir(bundled_synthgen):
        if _addon_dir not in sys.path:
            sys.path.insert(0, _addon_dir)
        schemas_root = os.path.join(_addon_dir, "data", "schemas")
    else:
        repo_root = os.path.normpath(os.path.join(_addon_dir, "..", ".."))
        src_path = os.path.join(repo_root, "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        schemas_root = os.path.join(repo_root, "data", "schemas")

    import synthgen.schema.query as sq
    sq._SCHEMAS_ROOT_OVERRIDE = schemas_root


def _teardown_paths():
    """Remove added paths from sys.path."""
    vendor = os.path.join(_addon_dir, "vendor")
    bundled_synthgen = os.path.join(_addon_dir, "synthgen")

    for p in [vendor, _addon_dir]:
        if p in sys.path:
            sys.path.remove(p)

    if not os.path.isdir(bundled_synthgen):
        repo_root = os.path.normpath(os.path.join(_addon_dir, "..", ".."))
        src_path = os.path.join(repo_root, "src")
        if src_path in sys.path:
            sys.path.remove(src_path)

    if "synthgen.schema.query" in sys.modules:
        sys.modules["synthgen.schema.query"]._SCHEMAS_ROOT_OVERRIDE = None


class SynthgenMCPPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    port: bpy.props.IntProperty(
        name="Port",
        description="SSE MCP server port",
        default=8400,
        min=1024,
        max=65535,
    )
    auto_start: bpy.props.BoolProperty(
        name="Auto-start Server",
        description="Start the MCP server automatically when addon is enabled",
        default=True,
    )
    log_level: bpy.props.EnumProperty(
        name="Log Level",
        items=[
            ("DEBUG", "Debug", ""),
            ("INFO", "Info", ""),
            ("WARNING", "Warning", ""),
            ("ERROR", "Error", ""),
        ],
        default="WARNING",
    )
    viewpoint: bpy.props.StringProperty(
        name="Agent Viewpoint",
        description=(
            "Default posture for AI agents connecting via MCP. "
            "Sets how agents think about Blender — procedural-first, "
            "traditional modeling, or custom. Clear for no viewpoint. "
            "Changes take effect after server restart."
        ),
        default=_DEFAULT_VIEWPOINT,
        maxlen=0,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "port")
        layout.prop(self, "auto_start")
        layout.prop(self, "log_level")
        layout.separator()
        layout.label(text="Agent Viewpoint:")

        box = layout.box()
        box.label(text=f"Active viewpoint: {len(self.viewpoint)} chars", icon="TEXT")
        row = box.row(align=True)
        row.operator("synthgen.open_viewpoint_editor", icon="WINDOW")
        row.operator("synthgen.apply_viewpoint", icon="FILE_REFRESH")
        row.operator("synthgen.reset_viewpoint", icon="LOOP_BACK")


class SYNTHGEN_OT_open_viewpoint_editor(bpy.types.Operator):
    bl_idname = "synthgen.open_viewpoint_editor"
    bl_label = "Edit Viewpoint"
    bl_description = "Open the viewpoint text in the system text editor"

    def execute(self, context):
        import subprocess
        import tempfile

        prefs = context.preferences.addons.get(__package__)
        content = prefs.preferences.viewpoint if prefs else _DEFAULT_VIEWPOINT

        viewpoint_dir = os.path.join(_addon_dir, ".viewpoint")
        os.makedirs(viewpoint_dir, exist_ok=True)
        filepath = os.path.join(viewpoint_dir, "viewpoint.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        if sys.platform == "win32":
            os.startfile(filepath)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", filepath])
        else:
            subprocess.Popen(["xdg-open", filepath])

        self.report({"INFO"}, f"Opened {filepath} — edit, save, then click Apply")
        return {"FINISHED"}


class SYNTHGEN_OT_apply_viewpoint(bpy.types.Operator):
    bl_idname = "synthgen.apply_viewpoint"
    bl_label = "Apply & Restart Server"
    bl_description = (
        "Read viewpoint.txt, save to preferences, and restart the MCP server"
    )

    def execute(self, context):
        filepath = os.path.join(_addon_dir, ".viewpoint", "viewpoint.txt")
        if os.path.isfile(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = _DEFAULT_VIEWPOINT

        prefs = context.preferences.addons.get(__package__)
        if prefs is None:
            self.report({"ERROR"}, "Synthgen MCP preferences not found")
            return {"CANCELLED"}
        prefs.preferences.viewpoint = content

        from . import server as srv
        from .ui import start_watchdog, stop_watchdog

        was_running = srv.is_running()
        stop_watchdog()
        srv.stop()
        if was_running:
            try:
                srv.start(prefs.preferences.port, _addon_dir, viewpoint=content)
                start_watchdog()
            except Exception as exc:
                self.report({"ERROR"}, f"Failed to restart server: {exc}")
                return {"CANCELLED"}
            self.report({"INFO"}, "Viewpoint applied and server restarted")
        else:
            self.report({"INFO"}, "Viewpoint applied (server not running)")
        return {"FINISHED"}


class SYNTHGEN_OT_reset_viewpoint(bpy.types.Operator):
    bl_idname = "synthgen.reset_viewpoint"
    bl_label = "Reset to Default"
    bl_description = "Reset the viewpoint file and preference to the default text"

    def execute(self, context):
        viewpoint_dir = os.path.join(_addon_dir, ".viewpoint")
        os.makedirs(viewpoint_dir, exist_ok=True)
        filepath = os.path.join(viewpoint_dir, "viewpoint.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(_DEFAULT_VIEWPOINT)
        self.report({"INFO"}, "Viewpoint file reset to default (click Apply to restart server)")
        return {"FINISHED"}


_classes = [
    SynthgenMCPPreferences,
    SYNTHGEN_OT_open_viewpoint_editor,
    SYNTHGEN_OT_apply_viewpoint,
    SYNTHGEN_OT_reset_viewpoint,
]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    _setup_paths()

    from . import deps
    vendor = os.path.join(_addon_dir, "vendor")
    if not deps.deps_installed():
        deps.install_deps(vendor)
        _setup_vendor(vendor)

    from . import ui
    ui.register()

    prefs = bpy.context.preferences.addons.get(__package__)
    if prefs and prefs.preferences.auto_start:
        bpy.app.timers.register(_deferred_start, first_interval=0.5)


def _deferred_start():
    """Start the server after Blender finishes initialization."""
    from . import server as srv
    from .ui import start_watchdog
    prefs = bpy.context.preferences.addons.get(__package__)
    port = prefs.preferences.port if prefs else 8400
    viewpoint = prefs.preferences.viewpoint if prefs else ""
    try:
        srv.start(port, _addon_dir, viewpoint=viewpoint)
        start_watchdog()
    except Exception:
        logger.exception("Failed to start MCP server")
    return None


def unregister():
    from . import server as srv
    from .ui import stop_watchdog
    stop_watchdog()
    srv.stop()

    from . import ui
    ui.unregister()

    if bpy.app.timers.is_registered(_deferred_start):
        bpy.app.timers.unregister(_deferred_start)

    _teardown_paths()

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
