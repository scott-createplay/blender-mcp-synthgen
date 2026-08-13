"""TransportBackend — abstraction over how we talk to Blender's bpy.

Two implementations:
  SocketTransport     — proxies through ahujasid/blender-mcp addon (GUI Blender)
  DirectBpyTransport  — imports bpy directly (headless / in-process)
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from abc import ABC, abstractmethod
from io import StringIO
from typing import Any

logger = logging.getLogger(__name__)


class TransportError(Exception):
    """Raised when the transport cannot reach Blender."""


class TransportBackend(ABC):
    def __init__(self):
        self._dirty = False

    @property
    def dirty(self) -> bool:
        """True if a Layer 2 mutation happened since the last graph resolve."""
        return self._dirty

    def mark_dirty(self) -> None:
        self._dirty = True

    def clear_dirty(self) -> None:
        self._dirty = False

    @abstractmethod
    def execute_python(self, code: str) -> Any:
        """Run Python code in Blender and return the result."""

    @abstractmethod
    def get_blender_version(self) -> tuple[int, int, int]:
        """Return the connected Blender's (major, minor, patch)."""

    @abstractmethod
    def close(self) -> None:
        """Clean up connection resources."""


class SocketTransport(TransportBackend):
    """Proxies through ahujasid/blender-mcp addon's TCP socket."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9876,
        timeout: float = 180.0,
        connect_timeout: float = 5.0,
    ):
        super().__init__()
        self._host = host
        self._port = port
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._version: tuple[int, int, int] | None = None

    def _close_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _connect(self) -> socket.socket:
        if self._sock is not None:
            return self._sock
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._connect_timeout)
        try:
            sock.connect((self._host, self._port))
        except ConnectionRefusedError:
            sock.close()
            raise TransportError(
                f"Cannot connect to Blender on {self._host}:{self._port} — "
                f"is the BlenderMCP addon started? "
                f"(N panel → BlenderMCP → Start Server)"
            )
        except (TimeoutError, socket.timeout):
            sock.close()
            raise TransportError(
                f"Connection to Blender on {self._host}:{self._port} timed out "
                f"after {self._connect_timeout}s — is Blender running with the "
                f"BlenderMCP addon started?"
            )
        except OSError as exc:
            sock.close()
            raise TransportError(
                f"Cannot connect to Blender on {self._host}:{self._port}: {exc}"
            ) from exc
        sock.settimeout(self._timeout)
        self._sock = sock
        logger.info("Connected to Blender at %s:%d", self._host, self._port)
        return sock

    def _send_command(self, cmd_type: str, params: dict | None = None) -> dict:
        with self._lock:
            try:
                return self._try_send(cmd_type, params)
            except (ConnectionError, OSError) as exc:
                logger.warning("Connection lost, reconnecting: %s", exc)
                self._close_socket()
                return self._try_send(cmd_type, params)

    def _try_send(self, cmd_type: str, params: dict | None = None) -> dict:
        sock = self._connect()
        msg: dict[str, Any] = {"type": cmd_type}
        if params:
            msg["params"] = params
        sock.sendall(json.dumps(msg).encode("utf-8"))

        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                raise ConnectionError("Blender closed the connection")
            chunks.append(chunk)
            try:
                return json.loads(b"".join(chunks).decode("utf-8"))
            except json.JSONDecodeError:
                continue

    def execute_python(self, code: str) -> Any:
        resp = self._send_command("execute_code", {"code": code})
        if resp.get("status") == "error":
            raise RuntimeError(f"Blender error: {resp.get('message', resp)}")
        return resp.get("result", resp)

    def get_blender_version(self) -> tuple[int, int, int]:
        if self._version is not None:
            return self._version
        result = self.execute_python(
            "import bpy, json; print(json.dumps(list(bpy.app.version)))"
        )
        output = result if isinstance(result, str) else result.get("output", "")
        parts = json.loads(output.strip())
        self._version = tuple(parts[:3])
        return self._version

    def close(self) -> None:
        self._close_socket()


class DirectBpyTransport(TransportBackend):
    """Calls bpy directly — for headless Blender or in-process use."""

    def __init__(self):
        super().__init__()
        try:
            import bpy as _bpy
            self._bpy = _bpy
        except ImportError:
            raise RuntimeError(
                "DirectBpyTransport requires bpy. Run inside Blender or install bpy."
            )

    def execute_python(self, code: str) -> Any:
        namespace = {"bpy": self._bpy}
        stdout_capture = StringIO()
        import contextlib
        with contextlib.redirect_stdout(stdout_capture):
            exec(code, namespace)
        output = stdout_capture.getvalue()
        return {"output": output} if output else {}

    def get_blender_version(self) -> tuple[int, int, int]:
        return tuple(self._bpy.app.version[:3])

    def close(self) -> None:
        pass


def auto_detect_transport() -> TransportBackend:
    """Pick the right transport based on the environment."""
    host = os.environ.get("BLENDER_HOST")
    port = os.environ.get("BLENDER_PORT")

    if host or port:
        return SocketTransport(
            host=host or "localhost",
            port=int(port) if port else 9876,
        )

    try:
        import bpy  # noqa: F401
        return DirectBpyTransport()
    except ImportError:
        pass

    return SocketTransport()
