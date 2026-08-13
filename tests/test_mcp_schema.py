"""Tests for MCP schema tools — structured JSON responses, error cases."""

import json
import pytest

from synthgen.schema.query import (
    data_find, data_show, data_socket, data_setting, load_schema,
)


@pytest.fixture()
def gn_nodes():
    schema, _ = load_schema("gn")
    return schema["nodes"]


@pytest.fixture()
def shader_nodes():
    schema, _ = load_schema("shader")
    return schema["nodes"]


class TestDataFind:
    def test_returns_list(self, gn_nodes):
        results = data_find(gn_nodes, "Distribute")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_result_structure(self, gn_nodes):
        results = data_find(gn_nodes, "Distribute")
        hit = results[0]
        assert "id" in hit
        assert "label" in hit
        assert "inputs" in hit
        assert "outputs" in hit

    def test_no_match_returns_empty(self, gn_nodes):
        results = data_find(gn_nodes, "xyzzy_nonexistent_9999")
        assert results == []

    def test_case_insensitive(self, gn_nodes):
        upper = data_find(gn_nodes, "DISTRIBUTE")
        lower = data_find(gn_nodes, "distribute")
        assert len(upper) == len(lower) > 0


class TestDataShow:
    def test_returns_dict(self, gn_nodes):
        result = data_show(gn_nodes, "GeometryNodeDistributePointsOnFaces")
        assert isinstance(result, dict)
        assert result["id"] == "GeometryNodeDistributePointsOnFaces"

    def test_has_sockets(self, gn_nodes):
        result = data_show(gn_nodes, "GeometryNodeDistributePointsOnFaces")
        assert len(result["inputs"]) > 0
        assert len(result["outputs"]) > 0
        inp = result["inputs"][0]
        assert "identifier" in inp
        assert "name" in inp
        assert "type" in inp

    def test_resolve_by_label(self, gn_nodes):
        result = data_show(gn_nodes, "Store Named Attribute")
        assert result["id"] == "GeometryNodeStoreNamedAttribute"

    def test_settings_included(self, gn_nodes):
        result = data_show(gn_nodes, "GeometryNodeStoreNamedAttribute")
        assert "settings" in result
        assert isinstance(result["settings"], list)


class TestDataSocket:
    def test_returns_list(self, gn_nodes):
        results = data_socket(gn_nodes, "Geometry")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_result_structure(self, gn_nodes):
        results = data_socket(gn_nodes, "Geometry")
        hit = results[0]
        assert "node_id" in hit
        assert "direction" in hit
        assert "identifier" in hit
        assert "type" in hit

    def test_direction_values(self, gn_nodes):
        results = data_socket(gn_nodes, "Geometry")
        directions = {r["direction"] for r in results}
        assert directions <= {"input", "output"}


class TestDataSetting:
    def test_returns_list(self, gn_nodes):
        results = data_setting(gn_nodes, "domain")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_result_structure(self, gn_nodes):
        results = data_setting(gn_nodes, "domain")
        hit = results[0]
        assert "node_id" in hit
        assert "setting" in hit
        assert "values" in hit


class TestSchemaToolsJSON:
    """Verify the MCP tool wrappers return valid JSON strings."""

    @pytest.fixture()
    def tools(self):
        from unittest.mock import MagicMock
        mock_mcp = MagicMock()
        registered = {}

        def capture_tool():
            def decorator(fn):
                registered[fn.__name__] = fn
                return fn
            return decorator

        mock_mcp.tool = capture_tool
        from synthgen.mcp.tools.schema import register
        register(mock_mcp, get_blender_dir=lambda: None)
        return registered

    def test_schema_find_returns_json(self, tools):
        result = tools["schema_find"]("Distribute", "gn")
        parsed = json.loads(result)
        assert "results" in parsed
        assert "count" in parsed
        assert parsed["count"] > 0

    def test_schema_show_returns_json(self, tools):
        result = tools["schema_show"]("GeometryNodeDistributePointsOnFaces", "gn")
        parsed = json.loads(result)
        assert "node" in parsed
        assert parsed["node"]["id"] == "GeometryNodeDistributePointsOnFaces"

    def test_schema_socket_returns_json(self, tools):
        result = tools["schema_socket"]("Geometry", "gn")
        parsed = json.loads(result)
        assert "results" in parsed
        assert parsed["count"] > 0

    def test_schema_setting_returns_json(self, tools):
        result = tools["schema_setting"]("domain", "gn")
        parsed = json.loads(result)
        assert "results" in parsed
        assert parsed["count"] > 0

    def test_invalid_tree_type_raises(self, tools):
        with pytest.raises(ValueError, match="Invalid tree_type"):
            tools["schema_find"]("x", "bogus")

    def test_shader_tree_type(self, tools):
        result = tools["schema_find"]("Principled", "shader")
        parsed = json.loads(result)
        assert parsed["count"] > 0

    def test_compositor_tree_type(self, tools):
        result = tools["schema_find"]("AlphaOver", "compositor")
        parsed = json.loads(result)
        assert parsed["count"] > 0
