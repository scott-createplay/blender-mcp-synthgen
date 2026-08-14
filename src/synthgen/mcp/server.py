"""Synthgen MCP server — grounded Blender tools over the Model Context Protocol.

Launch:
  python -m synthgen.mcp.server

Or configure in Claude Code / Cursor MCP settings:
  {"command": "python", "args": ["-m", "synthgen.mcp.server"]}

Transport auto-detection:
  - BLENDER_HOST / BLENDER_PORT env vars → SocketTransport (ahujasid addon)
  - bpy importable → DirectBpyTransport (headless)
  - Neither set → SocketTransport to localhost:9876 (default)
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from synthgen.mcp.transport import TransportBackend, auto_detect_transport

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "synthgen",
    instructions=(
        "Grounded Blender tools for procedural 3D synthetic data. "
        "Schema-validated node/socket identifiers, scene-graph introspection, "
        "and procedural authoring — never hallucinates Blender API names."
    ),
)

_transport: TransportBackend | None = None
_blender_dir: str | None = None


def _get_transport() -> TransportBackend:
    global _transport, _blender_dir
    if _transport is None:
        _transport = auto_detect_transport()
        logger.info("Transport: %s", type(_transport).__name__)
        try:
            from synthgen.schema.query import resolve_schema_dir
            version = _transport.get_blender_version()
            _blender_dir = resolve_schema_dir(version)
            logger.info("Blender %s → schema dir %s", version, _blender_dir)
        except Exception as exc:
            logger.warning("Could not detect Blender version for schema resolution: %s", exc)
    return _transport


def _get_blender_dir() -> str | None:
    return _blender_dir


# --- Register tools ---------------------------------------------------------

from synthgen.mcp.tools import schema as schema_tools
from synthgen.mcp.tools import graph as graph_tools
from synthgen.mcp.tools import blender as blender_tools
from synthgen.mcp.tools import verify as verify_tools
from synthgen.mcp.tools import pipeline as pipeline_tools

schema_tools.register(mcp, _get_blender_dir)
graph_tools.register(mcp, _get_transport)
blender_tools.register(mcp, _get_transport, _get_blender_dir)
verify_tools.register(mcp, _get_transport)
pipeline_tools.register(mcp, _get_transport, _get_blender_dir)


# --- Entry point ------------------------------------------------------------

def main():
    if sys.stdin.isatty():
        print(
            "synthgen-mcp: waiting for MCP client on stdin. "
            "This is normal — the server speaks JSON-RPC over stdio, not a human shell.",
            file=sys.stderr,
        )
    mcp.run()


if __name__ == "__main__":
    main()
