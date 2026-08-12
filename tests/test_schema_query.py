"""Offline smoke tests for the grounded-schema query — no Blender required."""

import pytest

from synthgen.schema import query


@pytest.mark.parametrize("key,tree", [
    ("gn", "GeometryNodeTree"),
    ("shader", "ShaderNodeTree"),
    ("compositor", "CompositorNodeTree"),
])
def test_schema_loads(key, tree):
    schema, path = query.load_schema(key)
    assert schema["tree_type"] == tree
    assert schema["node_count"] == len(schema["nodes"]) > 0


def test_label_vs_identifier_gotcha():
    """The whole reason grounding exists: label 'Group ID' -> identifier 'Group Index'."""
    schema, _ = query.load_schema("gn")
    acc = schema["nodes"]["GeometryNodeAccumulateField"]
    group = next(s for s in acc["inputs"] if s["name"] == "Group ID")
    assert group["identifier"] == "Group Index"


def test_shader_attribute_has_instancer_mode():
    """The attribute bridge depends on ShaderNodeAttribute's INSTANCER type."""
    schema, _ = query.load_schema("shader")
    attr = schema["nodes"]["ShaderNodeAttribute"]
    setting = next(s for s in attr["settings"] if s["name"] == "attribute_type")
    assert "INSTANCER" in setting["values"]


def test_resolve_by_label():
    schema, _ = query.load_schema("gn")
    nid, node = query.resolve(schema["nodes"], "Store Named Attribute")
    assert nid == "GeometryNodeStoreNamedAttribute"
