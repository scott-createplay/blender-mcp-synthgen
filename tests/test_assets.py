"""Offline tests for ``synthgen.assets`` — no Blender required."""

import os
import tempfile

import pytest

from synthgen.assets import (
    ValidationResult,
    validate,
    slug_from_name,
    catalog_uuid,
    ensure_catalog_entry,
    generate_manifest,
    CATEGORY_CATALOG,
)


# ---------------------------------------------------------------------------
# Minimal mock model
# ---------------------------------------------------------------------------

class MockInterfaceItem:
    def __init__(self, name, identifier, socket_type, in_out, default_value=None):
        self.name = name
        self.identifier = identifier
        self.socket_type = socket_type
        self.in_out = in_out
        self.default_value = default_value


class MockInterface:
    def __init__(self, items):
        self.items_tree = items


class MockNode:
    def __init__(self, name, bl_idname="GeometryNodeGroup"):
        self.name = name
        self.bl_idname = bl_idname


class MockTree:
    def __init__(self, name, nodes=None, interface_items=None, props=None):
        self.name = name
        self.bl_idname = "GeometryNodeTree"
        self.nodes = nodes or []
        self.interface = MockInterface(interface_items or [])
        self._props = props or {}

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value


# ---------------------------------------------------------------------------
# slug_from_name
# ---------------------------------------------------------------------------

class TestSlug:

    def test_basic(self):
        assert slug_from_name("SynthGen.Scatter on Surface") == "scatter_on_surface"

    def test_no_prefix(self):
        assert slug_from_name("My Group") == "my_group"

    def test_special_chars(self):
        assert slug_from_name("SynthGen.SDF Ops (v2)") == "sdf_ops_v2"

    def test_already_slugged(self):
        assert slug_from_name("SynthGen.simple") == "simple"


# ---------------------------------------------------------------------------
# catalog_uuid
# ---------------------------------------------------------------------------

class TestCatalogUUID:

    def test_deterministic(self):
        a = catalog_uuid("Test")
        b = catalog_uuid("Test")
        assert a == b

    def test_different_names(self):
        assert catalog_uuid("A") != catalog_uuid("B")

    def test_is_valid_uuid(self):
        import uuid
        uuid.UUID(catalog_uuid("Test"))


# ---------------------------------------------------------------------------
# ensure_catalog_entry
# ---------------------------------------------------------------------------

class TestEnsureCatalogEntry:

    def test_creates_new_file(self, tmp_path):
        cat = str(tmp_path / "blender_assets.cats.txt")
        uid = ensure_catalog_entry(cat, "Distribution")
        assert uid == CATEGORY_CATALOG["Distribution"][0]
        with open(cat) as f:
            content = f.read()
        assert "Distribution" in content

    def test_idempotent(self, tmp_path):
        cat = str(tmp_path / "blender_assets.cats.txt")
        ensure_catalog_entry(cat, "Distribution")
        ensure_catalog_entry(cat, "Distribution")
        with open(cat) as f:
            content = f.read()
        assert content.count("Distribution") == 2  # path + simple-name

    def test_appends_to_existing(self, tmp_path):
        cat = str(tmp_path / "blender_assets.cats.txt")
        ensure_catalog_entry(cat, "Distribution")
        ensure_catalog_entry(cat, "Camera")
        with open(cat) as f:
            content = f.read()
        assert "Distribution" in content
        assert "Camera" in content

    def test_unknown_category(self, tmp_path):
        cat = str(tmp_path / "blender_assets.cats.txt")
        uid = ensure_catalog_entry(cat, "Custom")
        assert uid == catalog_uuid("Custom")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

class TestValidate:

    def _tagged_tree(self, **kwargs):
        props = kwargs.pop("props", {"synthgen_asset": "SynthGen.Test"})
        interface = kwargs.pop("interface_items", [
            MockInterfaceItem("Geometry", "Socket_0", "NodeSocketGeometry", "INPUT"),
            MockInterfaceItem("Geometry", "Socket_1", "NodeSocketGeometry", "OUTPUT"),
        ])
        return MockTree("SynthGen.Test", props=props, interface_items=interface, **kwargs)

    def test_valid_tree(self):
        tree = self._tagged_tree()
        result = validate(tree)
        assert result.ok

    def test_not_tagged(self):
        tree = self._tagged_tree(props={})
        result = validate(tree)
        assert not result.ok
        assert any("not tagged" in e for e in result.errors)

    def test_no_interface(self):
        tree = self._tagged_tree(interface_items=[])
        result = validate(tree)
        assert not result.ok
        assert any("no interface" in e.lower() for e in result.errors)

    def test_missing_prefix_warning(self):
        tree = MockTree(
            "MyGroup",
            props={"synthgen_asset": "MyGroup"},
            interface_items=[
                MockInterfaceItem("Geo", "S0", "NodeSocketGeometry", "INPUT"),
            ],
        )
        result = validate(tree)
        assert result.ok
        assert any("prefix" in w.lower() for w in result.warnings)

    def test_viewer_node_warning(self):
        tree = self._tagged_tree(
            nodes=[MockNode("Viewer", "GeometryNodeViewer")],
        )
        result = validate(tree)
        assert result.ok
        assert any("viewer" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# generate_manifest
# ---------------------------------------------------------------------------

class TestGenerateManifest:

    def test_has_frontmatter(self):
        tree = MockTree(
            "SynthGen.Test Asset",
            interface_items=[
                MockInterfaceItem("Geometry", "Socket_0", "NodeSocketGeometry", "INPUT"),
                MockInterfaceItem("Density", "Socket_1", "NodeSocketFloat", "INPUT", 10.0),
                MockInterfaceItem("Geometry", "Socket_2", "NodeSocketGeometry", "OUTPUT"),
            ],
            props={"synthgen_asset": "SynthGen.Test Asset"},
        )
        md = generate_manifest(tree, "Distribution", version="0.1")
        assert "asset: SynthGen.Test Asset" in md
        assert "file: test_asset.blend" in md
        assert "category: distribution" in md

    def test_socket_table(self):
        tree = MockTree(
            "SynthGen.Test",
            interface_items=[
                MockInterfaceItem("Count", "Socket_1", "NodeSocketInt", "INPUT", 100),
                MockInterfaceItem("Name", "Socket_2", "NodeSocketString", "INPUT", "test"),
            ],
            props={"synthgen_asset": "SynthGen.Test"},
        )
        md = generate_manifest(tree, "Utility")
        assert "| Count | Socket_1 | Int | 100 |" in md
        assert '| Name | Socket_2 | String | "test" |' in md

    def test_empty_sections(self):
        tree = MockTree(
            "SynthGen.Test",
            interface_items=[],
            props={"synthgen_asset": "SynthGen.Test"},
        )
        md = generate_manifest(tree, "Utility")
        assert "## Composes with" in md
        assert "## Limitations" in md
