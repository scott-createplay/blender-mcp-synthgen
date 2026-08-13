"""Offline tests: snapshot backend + traversal algorithms against tiny_scene.json."""

import os

import pytest

from synthgen.scenegraph import traverse
from synthgen.scenegraph.backend_snapshot import SnapshotGraph

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "tiny_scene.json")


@pytest.fixture
def g():
    return SnapshotGraph.from_file(FIXTURE)


def test_resolve_and_kinds(g):
    assert g.resolve("OBJ:Willow")["kind"] == "object"
    node = g.resolve("MAT:Bark/NODE:Attribute")
    assert node["data"]["attribute_type"] == "INSTANCER"


def test_neighbors_filter(g):
    types = {e.type for e in g.neighbors("OBJ:Willow")}
    assert types == {"parent", "has_modifier", "uses_material"}
    only = list(g.neighbors("OBJ:Willow", {"uses_material"}))
    assert len(only) == 1 and only[0].dst == "MAT:Bark"


def test_reachable_dependency_closure(g):
    reach = traverse.reachable(g, "OBJ:Willow")
    # Willow transitively depends on its modifier, tree, GN node, material, shader node, ground
    assert {"OBJ:Willow/MOD:GeometryNodes", "NG:WillowGrowth",
            "NG:WillowGrowth/NODE:StoreNamedAttribute", "MAT:Bark",
            "MAT:Bark/NODE:Attribute", "OBJ:Ground"} <= reach


def test_path(g):
    p = traverse.path(g, "OBJ:Willow", "NG:WillowGrowth/NODE:StoreNamedAttribute")
    assert [e.type for e in p] == ["has_modifier", "modifier_uses_tree", "tree_contains_node"]


def test_attribute_trace_finds_bridge(g):
    res = traverse.attribute_trace(g, "bark_age")
    assert len(res["edges"]) == 1
    e = res["edges"][0]
    assert e.type == "attr_bridge" and e.tier == 2 and e.state_dependent
    assert e.src == "MAT:Bark/NODE:Attribute"
    assert e.dst == "NG:WillowGrowth/NODE:StoreNamedAttribute"


def test_attribute_trace_dead_bridge(g):
    assert traverse.attribute_trace(g, "does_not_exist")["edges"] == []


def test_impact_set_over_dataflow(g):
    # "If I change the Store node, what breaks?" — following the attribute bridge only.
    impacted = traverse.impact_set(
        g, "NG:WillowGrowth/NODE:StoreNamedAttribute", edge_types={"attr_bridge"})
    assert impacted == {"MAT:Bark/NODE:Attribute"}


# --- attr_bridge snapshot tests (matching the live resolver) ------------------

BRIDGE_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "bridge_scene.json")


@pytest.fixture
def bg():
    return SnapshotGraph.from_file(BRIDGE_FIXTURE)


def test_bridge_edge_properties(bg):
    edges = list(bg.neighbors("MAT:TestMaterial/NODE:Attribute", {"attr_bridge"}))
    assert len(edges) == 1
    e = edges[0]
    assert e.src == "MAT:TestMaterial/NODE:Attribute"
    assert e.dst == "NG:GN_TestTree/NODE:Store Named Attribute"
    assert e.tier == 2
    assert e.state_dependent is True
    assert e.data["attr"] == "inst_color"
    assert e.data["confirmed_by_eval"] is True


def test_bridge_attribute_trace(bg):
    res = traverse.attribute_trace(bg, "inst_color")
    assert len(res["edges"]) == 1
    assert res["edges"][0].data["attr"] == "inst_color"


def test_bridge_impact_set(bg):
    impacted = traverse.impact_set(
        bg, "NG:GN_TestTree/NODE:Store Named Attribute", edge_types={"attr_bridge"})
    assert impacted == {"MAT:TestMaterial/NODE:Attribute"}


def test_bridge_reachable_includes_writer(bg):
    reach = traverse.reachable(bg, "MAT:TestMaterial/NODE:Attribute")
    assert "NG:GN_TestTree/NODE:Store Named Attribute" in reach


def test_bridge_dead_attr(bg):
    assert traverse.attribute_trace(bg, "nonexistent")["edges"] == []
