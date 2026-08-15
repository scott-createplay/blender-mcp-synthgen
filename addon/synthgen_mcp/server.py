"""SSE MCP server lifecycle — start/stop the FastMCP server in a daemon thread."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_executor = None
_transport = None
_server_thread: threading.Thread | None = None
_shutdown_event = threading.Event()
_port: int = 8400
_last_error: str | None = None
_start_time: float | None = None
_tool_count: int = 0
_tools_hash: str | None = None
_blender_version: str | None = None
_addon_version: str | None = None


def _build_and_run(port: int, addon_dir: str) -> None:
    """Build the FastMCP instance, register tools, and run SSE server.

    This runs in a daemon thread. Blocks until the server shuts down.
    """
    global _transport
    try:
        from mcp.server.fastmcp import FastMCP

        from .executor import AddonTransport, MainThreadExecutor

        _transport = AddonTransport(_executor)

        from synthgen.schema.query import resolve_schema_dir

        version = _transport.get_blender_version()
        blender_dir = resolve_schema_dir(version)

        from synthgen.mcp.tools.compat import build_server_instructions

        mcp = FastMCP(
            "synthgen",
            host="127.0.0.1",
            port=port,
            instructions=build_server_instructions(version),
        )
        logger.info("Blender %s → schema dir %s", version, blender_dir)

        get_transport = lambda: _transport
        get_blender_dir = lambda: blender_dir
        get_blender_version = lambda: version

        from synthgen.mcp.tools import (
            blender as blender_tools,
            graph as graph_tools,
            pipeline as pipeline_tools,
            schema as schema_tools,
            verify as verify_tools,
        )

        schema_tools.register(mcp, get_blender_dir)
        graph_tools.register(mcp, get_transport)
        blender_tools.register(mcp, get_transport, get_blender_dir, get_blender_version)
        verify_tools.register(mcp, get_transport, get_blender_version)
        pipeline_tools.register(mcp, get_transport, get_blender_dir, get_blender_version)

        global _tool_count, _tools_hash, _blender_version, _addon_version
        try:
            tools = mcp._tool_manager._tools
            _tool_count = len(tools)
            names = sorted(tools.keys())
            _tools_hash = hashlib.sha256("|".join(names).encode()).hexdigest()[:12]
        except AttributeError:
            _tool_count = 0
            _tools_hash = None

        _blender_version = ".".join(str(v) for v in version)

        try:
            import sys as _sys
            _pkg = _sys.modules.get(__package__)
            if _pkg and hasattr(_pkg, "bl_info"):
                _addon_version = ".".join(str(v) for v in _pkg.bl_info["version"])
        except Exception:
            _addon_version = None

        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response

        @mcp.custom_route("/health", methods=["GET"])
        async def health(request: Request) -> Response:
            return JSONResponse(get_status())

        logger.info("SSE MCP server starting on 127.0.0.1:%d (%d tools)", port, _tool_count)
        mcp.run(transport="sse")

    except Exception as exc:
        global _last_error
        _last_error = f"{type(exc).__name__}: {exc}"
        logger.exception("MCP server thread crashed")


def start(port: int, addon_dir: str) -> None:
    """Start the SSE MCP server in a background daemon thread."""
    global _executor, _server_thread, _port, _shutdown_event

    if _server_thread is not None and _server_thread.is_alive():
        logger.warning("Server already running on port %d", _port)
        return

    from .executor import MainThreadExecutor

    global _last_error, _start_time, _tool_count
    _port = port
    _last_error = None
    _start_time = time.monotonic()
    _tool_count = 0
    _shutdown_event.clear()

    _executor = MainThreadExecutor()
    _executor.start()

    _server_thread = threading.Thread(
        target=_build_and_run,
        args=(port, addon_dir),
        daemon=True,
        name="synthgen-mcp-sse",
    )
    _server_thread.start()
    logger.info("MCP server thread started")


def stop() -> None:
    """Stop the MCP server and executor."""
    global _executor, _server_thread, _transport, _start_time

    _shutdown_event.set()

    if _executor is not None:
        _executor.stop()
        _executor = None

    _transport = None
    _server_thread = None
    _start_time = None
    logger.info("MCP server stopped")


def is_running() -> bool:
    """Check if the server thread is alive."""
    return _server_thread is not None and _server_thread.is_alive()


def get_port() -> int:
    """Return the currently configured port."""
    return _port


def get_last_error() -> str | None:
    """Return the last server error, if any."""
    return _last_error


def get_uptime() -> float | None:
    """Return seconds since server started, or None if not running."""
    if _start_time is None or not is_running():
        return None
    return time.monotonic() - _start_time


def get_tool_count() -> int:
    """Return the number of registered MCP tools."""
    return _tool_count


def get_status() -> dict:
    """Return server health status as a dict (also served at /health)."""
    running = is_running()
    uptime = get_uptime()
    return {
        "status": "ok" if running else "stopped",
        "port": _port,
        "tools": _tool_count,
        "tools_hash": _tools_hash,
        "addon_version": _addon_version,
        "blender_version": _blender_version,
        "uptime_seconds": round(uptime, 1) if uptime is not None else None,
        "error": _last_error,
    }
