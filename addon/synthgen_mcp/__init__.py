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
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Synthgen MCP",
    "description": "Procedural 3D synthetic data tools via MCP (SSE server)",
    "category": "Development",
}

_addon_dir = os.path.dirname(os.path.abspath(__file__))


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

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "port")
        layout.prop(self, "auto_start")
        layout.prop(self, "log_level")


_classes = [SynthgenMCPPreferences]


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    _setup_paths()

    from . import deps
    if not deps.deps_installed():
        deps.install_deps(os.path.join(_addon_dir, "vendor"))
        if os.path.join(_addon_dir, "vendor") not in sys.path:
            sys.path.insert(0, os.path.join(_addon_dir, "vendor"))

    from . import ui
    ui.register()

    prefs = bpy.context.preferences.addons.get(__package__)
    if prefs and prefs.preferences.auto_start:
        bpy.app.timers.register(_deferred_start, first_interval=0.5)


def _deferred_start():
    """Start the server after Blender finishes initialization."""
    from . import server as srv
    prefs = bpy.context.preferences.addons.get(__package__)
    port = prefs.preferences.port if prefs else 8400
    try:
        srv.start(port, _addon_dir)
    except Exception:
        logger.exception("Failed to start MCP server")
    return None


def unregister():
    from . import server as srv
    srv.stop()

    from . import ui
    ui.unregister()

    if bpy.app.timers.is_registered(_deferred_start):
        bpy.app.timers.unregister(_deferred_start)

    _teardown_paths()

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
