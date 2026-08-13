"""Tests for MCP graph tools — preamble consistency, code generation."""

import json
from unittest.mock import MagicMock

import pytest

from synthgen.mcp.tools.graph import _PREAMBLE, _src_path


class TestPreamble:
    def test_src_path_is_absolute(self):
        import os
        assert os.path.isabs(_src_path())

    def test_src_path_points_to_src(self):
        import os
        assert os.path.isdir(_src_path())
        assert os.path.isdir(os.path.join(_src_path(), "synthgen"))

    def test_preamble_contains_sys_path(self):
        assert "sys.path.insert" in _PREAMBLE
        assert _src_path() in _PREAMBLE

    def test_preamble_imports_json(self):
        assert "import sys, os, json" in _PREAMBLE


class TestGraphToolCodeGen:
    """Verify all graph tools generate code starting with the same preamble."""

    @pytest.fixture()
    def tools_and_codes(self):
        """Register graph tools with a mock transport that captures generated code."""
        mock_mcp = MagicMock()
        registered = {}
        captured_codes = []

        def capture_tool():
            def decorator(fn):
                registered[fn.__name__] = fn
                return fn
            return decorator

        mock_mcp.tool = capture_tool

        mock_transport = MagicMock()
        mock_transport.execute_python.side_effect = lambda code: (
            captured_codes.append(code) or {"output": "[]"}
        )

        from synthgen.mcp.tools.graph import register
        register(mock_mcp, lambda: mock_transport)
        return registered, captured_codes

    def test_all_tools_use_same_preamble(self, tools_and_codes):
        tools, codes = tools_and_codes
        tool_names = [
            "graph_nodes", "graph_neighbors", "graph_reachable",
            "graph_impact_set", "graph_attribute_trace", "graph_snapshot",
        ]
        for name in tool_names:
            codes.clear()
            fn = tools[name]
            # Provide required args
            if name == "graph_neighbors":
                fn("OBJ:Cube")
            elif name in ("graph_reachable", "graph_impact_set"):
                fn("OBJ:Cube", None)
            elif name == "graph_attribute_trace":
                fn("test_attr")
            else:
                fn()

            assert len(codes) == 1, f"{name} should generate exactly one code block"
            assert codes[0].startswith(_PREAMBLE), (
                f"{name} does not start with the standard preamble"
            )
