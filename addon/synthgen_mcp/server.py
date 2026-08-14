"""SSE MCP server lifecycle — start/stop the FastMCP server in a daemon thread."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_executor = None
_transport = None
_server_thread: threading.Thread | None = None
_shutdown_event = threading.Event()
_port: int = 8400


def _build_and_run(port: int, addon_dir: str) -> None:
    """Build the FastMCP instance, register tools, and run SSE server.

    This runs in a daemon thread. Blocks until the server shuts down.
    """
    global _transport
    try:
        from mcp.server.fastmcp import FastMCP

        from .executor import AddonTransport, MainThreadExecutor

        mcp = FastMCP(
            "synthgen",
            host="127.0.0.1",
            port=port,
            instructions=(
                "Grounded Blender tools for procedural 3D synthetic data. "
                "Schema-validated node/socket identifiers, scene-graph introspection, "
                "and procedural authoring — never hallucinates Blender API names."
            ),
        )

        _transport = AddonTransport(_executor)

        from synthgen.schema.query import resolve_schema_dir

        version = _transport.get_blender_version()
        blender_dir = resolve_schema_dir(version)
        logger.info("Blender %s → schema dir %s", version, blender_dir)

        get_transport = lambda: _transport
        get_blender_dir = lambda: blender_dir

        from synthgen.mcp.tools import (
            blender as blender_tools,
            graph as graph_tools,
            pipeline as pipeline_tools,
            schema as schema_tools,
            verify as verify_tools,
        )

        schema_tools.register(mcp, get_blender_dir)
        graph_tools.register(mcp, get_transport)
        blender_tools.register(mcp, get_transport, get_blender_dir)
        verify_tools.register(mcp, get_transport)
        pipeline_tools.register(mcp, get_transport, get_blender_dir)

        logger.info("SSE MCP server starting on 127.0.0.1:%d", port)
        mcp.run(transport="sse")

    except Exception:
        logger.exception("MCP server thread crashed")


def start(port: int, addon_dir: str) -> None:
    """Start the SSE MCP server in a background daemon thread."""
    global _executor, _server_thread, _port, _shutdown_event

    if _server_thread is not None and _server_thread.is_alive():
        logger.warning("Server already running on port %d", _port)
        return

    from .executor import MainThreadExecutor

    _port = port
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
    global _executor, _server_thread, _transport

    _shutdown_event.set()

    if _executor is not None:
        _executor.stop()
        _executor = None

    _transport = None
    _server_thread = None
    logger.info("MCP server stopped")


def is_running() -> bool:
    """Check if the server thread is alive."""
    return _server_thread is not None and _server_thread.is_alive()


def get_port() -> int:
    """Return the currently configured port."""
    return _port
