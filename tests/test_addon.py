"""Offline tests for the Blender addon — executor, transport, build, deps."""

import io
import os
import queue
import sys
import textwrap
import threading
import zipfile
from concurrent.futures import Future
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# MainThreadExecutor tests (mock bpy.app.timers)
# ---------------------------------------------------------------------------

@pytest.fixture
def executor():
    """Create a MainThreadExecutor with bpy mocked out."""
    with mock.patch.dict(sys.modules, {"bpy": mock.MagicMock()}):
        # Re-import with bpy mocked
        import importlib
        addon_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "addon", "synthgen_mcp")
        )
        if addon_dir not in sys.path:
            sys.path.insert(0, os.path.dirname(addon_dir))
        try:
            from synthgen_mcp.executor import MainThreadExecutor
            exc = MainThreadExecutor(poll_interval=0.001)
            exc._running = True
            yield exc
        finally:
            if os.path.dirname(addon_dir) in sys.path:
                sys.path.remove(os.path.dirname(addon_dir))
            for mod_name in list(sys.modules):
                if mod_name.startswith("synthgen_mcp"):
                    del sys.modules[mod_name]


class TestMainThreadExecutor:
    def test_submit_returns_future(self, executor):
        future = executor.submit("x = 1")
        assert isinstance(future, Future)

    def test_poll_executes_code(self, executor):
        future = executor.submit("print('hello')")
        executor._poll()
        result = future.result(timeout=1)
        assert result["output"].strip() == "hello"

    def test_poll_multiple_items(self, executor):
        f1 = executor.submit("print('one')")
        f2 = executor.submit("print('two')")
        executor._poll()
        assert f1.result(timeout=1)["output"].strip() == "one"
        assert f2.result(timeout=1)["output"].strip() == "two"

    def test_poll_exception_propagates(self, executor):
        future = executor.submit("raise ValueError('boom')")
        executor._poll()
        with pytest.raises(ValueError, match="boom"):
            future.result(timeout=1)

    def test_poll_returns_interval_when_running(self, executor):
        interval = executor._poll()
        assert interval == executor._poll_interval

    def test_poll_returns_none_when_stopped(self, executor):
        executor._running = False
        interval = executor._poll()
        assert interval is None

    def test_empty_output_returns_empty_dict(self, executor):
        future = executor.submit("x = 42")
        executor._poll()
        assert future.result(timeout=1) == {}

    def test_cancelled_future_skipped(self, executor):
        future = executor.submit("print('should not run')")
        future.cancel()
        executor._poll()
        assert future.cancelled()


# ---------------------------------------------------------------------------
# AddonTransport tests
# ---------------------------------------------------------------------------

@pytest.fixture
def addon_transport():
    """Create an AddonTransport with a mock executor."""
    with mock.patch.dict(sys.modules, {"bpy": mock.MagicMock()}):
        addon_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "addon", "synthgen_mcp")
        )
        if os.path.dirname(addon_dir) not in sys.path:
            sys.path.insert(0, os.path.dirname(addon_dir))
        try:
            from synthgen_mcp.executor import AddonTransport, MainThreadExecutor
            mock_executor = MainThreadExecutor()
            mock_executor._running = True
            transport = AddonTransport(mock_executor)
            yield transport, mock_executor
        finally:
            if os.path.dirname(addon_dir) in sys.path:
                sys.path.remove(os.path.dirname(addon_dir))
            for mod_name in list(sys.modules):
                if mod_name.startswith("synthgen_mcp"):
                    del sys.modules[mod_name]


class TestAddonTransport:
    def test_execute_python(self, addon_transport):
        transport, executor = addon_transport
        future = transport._executor.submit("print('test')")
        executor._poll()
        result = future.result(timeout=1)
        assert "output" in result

    def test_dirty_flag_default(self, addon_transport):
        transport, _ = addon_transport
        assert not transport.dirty

    def test_mark_dirty(self, addon_transport):
        transport, _ = addon_transport
        transport.mark_dirty()
        assert transport.dirty

    def test_clear_dirty(self, addon_transport):
        transport, _ = addon_transport
        transport.mark_dirty()
        transport.clear_dirty()
        assert not transport.dirty


# ---------------------------------------------------------------------------
# Build script tests
# ---------------------------------------------------------------------------

class TestBuildScript:
    def test_build_creates_zip(self, tmp_path):
        """Test that the build script creates a valid addon zip."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "scripts"
        ))
        try:
            from build_addon import build
            output = str(tmp_path / "test_addon.zip")
            result = build(output)
            assert os.path.isfile(result)
            assert zipfile.is_zipfile(result)
        finally:
            sys.path.pop(0)
            if "build_addon" in sys.modules:
                del sys.modules["build_addon"]

    def test_zip_contains_required_files(self, tmp_path):
        """Test that the zip contains all expected addon files."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "scripts"
        ))
        try:
            from build_addon import build
            output = str(tmp_path / "test_addon.zip")
            build(output)

            with zipfile.ZipFile(output, "r") as zf:
                names = zf.namelist()

            expected = [
                "synthgen_mcp/__init__.py",
                "synthgen_mcp/executor.py",
                "synthgen_mcp/server.py",
                "synthgen_mcp/ui.py",
                "synthgen_mcp/deps.py",
            ]
            for f in expected:
                assert f in names, f"{f} missing from zip"

            synthgen_files = [n for n in names if n.startswith("synthgen_mcp/synthgen/")]
            assert len(synthgen_files) > 0, "No synthgen package files in zip"

            schema_files = [n for n in names if n.startswith("synthgen_mcp/data/schemas/")]
            assert len(schema_files) > 0, "No schema files in zip"
        finally:
            sys.path.pop(0)
            if "build_addon" in sys.modules:
                del sys.modules["build_addon"]

    def test_zip_excludes_pycache(self, tmp_path):
        """Test that __pycache__ directories are excluded."""
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "scripts"
        ))
        try:
            from build_addon import build
            output = str(tmp_path / "test_addon.zip")
            build(output)

            with zipfile.ZipFile(output, "r") as zf:
                names = zf.namelist()

            pycache = [n for n in names if "__pycache__" in n]
            assert len(pycache) == 0, f"__pycache__ found in zip: {pycache}"
        finally:
            sys.path.pop(0)
            if "build_addon" in sys.modules:
                del sys.modules["build_addon"]


# ---------------------------------------------------------------------------
# Deps module tests
# ---------------------------------------------------------------------------

class TestDeps:
    def test_deps_installed_when_mcp_available(self):
        with mock.patch.dict(sys.modules, {"bpy": mock.MagicMock()}):
            addon_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", "addon", "synthgen_mcp")
            )
            sys.path.insert(0, os.path.dirname(addon_dir))
            try:
                from synthgen_mcp.deps import deps_installed
                assert deps_installed()
            finally:
                sys.path.remove(os.path.dirname(addon_dir))
                for mod_name in list(sys.modules):
                    if mod_name.startswith("synthgen_mcp"):
                        del sys.modules[mod_name]

    def test_deps_not_installed_when_mcp_missing(self):
        with mock.patch.dict(sys.modules, {"bpy": mock.MagicMock(), "mcp": None}):
            addon_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", "addon", "synthgen_mcp")
            )
            sys.path.insert(0, os.path.dirname(addon_dir))
            try:
                import importlib
                from synthgen_mcp import deps
                importlib.reload(deps)
                assert not deps.deps_installed()
            finally:
                sys.path.remove(os.path.dirname(addon_dir))
                for mod_name in list(sys.modules):
                    if mod_name.startswith("synthgen_mcp"):
                        del sys.modules[mod_name]


# ---------------------------------------------------------------------------
# Schema root override tests
# ---------------------------------------------------------------------------

class TestSchemaRootOverride:
    def test_override_is_used(self):
        from synthgen.schema.query import _schemas_root, _SCHEMAS_ROOT_OVERRIDE
        import synthgen.schema.query as sq
        original = sq._SCHEMAS_ROOT_OVERRIDE
        try:
            sq._SCHEMAS_ROOT_OVERRIDE = "/custom/path"
            assert _schemas_root() == "/custom/path"
        finally:
            sq._SCHEMAS_ROOT_OVERRIDE = original

    def test_default_without_override(self):
        from synthgen.schema.query import _schemas_root
        import synthgen.schema.query as sq
        original = sq._SCHEMAS_ROOT_OVERRIDE
        try:
            sq._SCHEMAS_ROOT_OVERRIDE = None
            root = _schemas_root()
            assert root.endswith(os.path.join("data", "schemas"))
        finally:
            sq._SCHEMAS_ROOT_OVERRIDE = original
