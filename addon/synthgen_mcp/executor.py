"""Main-thread executor — marshals Python code execution to Blender's main thread.

bpy is main-thread-only. The SSE MCP server runs in a background thread.
This module bridges the gap with a queue + bpy.app.timers polling loop +
concurrent.futures.Future for result delivery.
"""

from __future__ import annotations

import contextlib
import io
import logging
import queue
import threading
from concurrent.futures import Future
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False


class MainThreadExecutor:
    """Queue-based executor that runs Python code on Blender's main thread."""

    def __init__(self, poll_interval: float = 0.01):
        self._queue: queue.Queue[tuple[str, Future]] = queue.Queue()
        self._poll_interval = poll_interval
        self._running = False
        self._lock = threading.Lock()

    def submit(self, code: str) -> Future:
        """Submit code for main-thread execution. Returns a Future."""
        future: Future = Future()
        self._queue.put((code, future))
        return future

    def _poll(self) -> float | None:
        """Called by bpy.app.timers on the main thread."""
        try:
            while True:
                try:
                    code, future = self._queue.get_nowait()
                except queue.Empty:
                    break
                if future.cancelled():
                    continue
                try:
                    result = self._execute(code)
                    future.set_result(result)
                except Exception as exc:
                    future.set_exception(exc)
        except Exception:
            logger.exception("Executor poll error")
        return self._poll_interval if self._running else None

    @staticmethod
    def _execute(code: str) -> dict:
        """Execute Python code, capturing stdout."""
        namespace: dict[str, Any] = {}
        if _HAS_BPY:
            import bpy as _bpy
            namespace["bpy"] = _bpy
        stdout_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture):
            exec(code, namespace)
        output = stdout_capture.getvalue()
        return {"output": output} if output else {}

    def start(self) -> None:
        """Register the timer to start polling the queue."""
        with self._lock:
            if self._running:
                return
            self._running = True
            if _HAS_BPY:
                bpy.app.timers.register(self._poll, persistent=True)
                logger.info("Main-thread executor started (%.0fms poll)", self._poll_interval * 1000)

    def stop(self) -> None:
        """Unregister the timer and drain the queue."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            if _HAS_BPY and bpy.app.timers.is_registered(self._poll):
                bpy.app.timers.unregister(self._poll)
            while not self._queue.empty():
                try:
                    _, future = self._queue.get_nowait()
                    future.cancel()
                except queue.Empty:
                    break
            logger.info("Main-thread executor stopped")

    @property
    def is_running(self) -> bool:
        return self._running


class AddonTransport:
    """TransportBackend that marshals execution through MainThreadExecutor.

    Deliberately does NOT inherit from TransportBackend to avoid importing
    the transport module at class-definition time (it pulls in socket/threading
    which is fine, but we want the addon to be self-contained). Instead it
    duck-types the interface and the server module wraps it properly.
    """

    def __init__(self, executor: MainThreadExecutor):
        self._executor = executor
        self._dirty = False

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        self._dirty = True

    def clear_dirty(self) -> None:
        self._dirty = False

    def execute_python(self, code: str) -> Any:
        future = self._executor.submit(code)
        return future.result(timeout=180)

    def get_blender_version(self) -> tuple[int, int, int]:
        if _HAS_BPY:
            import bpy as _bpy
            return tuple(_bpy.app.version[:3])
        return (0, 0, 0)

    def close(self) -> None:
        pass
