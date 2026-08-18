"""Offline tests for the SynthGen Blender addon operators and menus.

Mocks ``bpy`` entirely so ``addon/synthgen_mcp/operators.py`` and
``addon/synthgen_mcp/menus.py`` can be imported and exercised without a live
Blender session. ``bpy.types.Operator`` / ``bpy.types.Menu`` are given real
(non-mock) base classes because Python's class statement can't reliably
subclass a ``MagicMock`` instance (it silently produces a mock, not a real
subclass) — every other ``bpy.*`` attribute stays a plain ``MagicMock``.
"""

import importlib.util
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

import pytest


ADDON_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "addon", "synthgen_mcp")
)
SCRIPTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)


# ---------------------------------------------------------------------------
# Fake bpy module
# ---------------------------------------------------------------------------

class _FakeOperator:
    """Stand-in for ``bpy.types.Operator`` — subclassable + records reports."""

    bl_options = set()

    def __init__(self):
        self.reports_log = []

    def report(self, level, message):
        self.reports_log.append((level, message))


class _FakeMenu:
    """Stand-in for ``bpy.types.Menu``."""

    def __init__(self):
        self.layout = mock.MagicMock()


def _make_fake_bpy():
    fake = mock.MagicMock(name="bpy")
    fake.types.Operator = _FakeOperator
    fake.types.Menu = _FakeMenu
    fake.props.StringProperty = lambda **kw: kw
    fake.props.EnumProperty = lambda **kw: kw
    fake.props.BoolProperty = lambda **kw: kw
    fake.props.IntProperty = lambda **kw: kw
    return fake


def _load_module(name, filename, fake_bpy, source_dir=ADDON_DIR):
    """Import a script file fresh with *fake_bpy* patched into sys.modules."""
    path = os.path.join(source_dir, filename)
    with mock.patch.dict(sys.modules, {"bpy": fake_bpy}):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    return module


@pytest.fixture
def fake_bpy():
    return _make_fake_bpy()


@pytest.fixture
def operators_module(fake_bpy):
    module = _load_module("_test_operators_mod", "operators.py", fake_bpy)
    yield module
    sys.modules.pop("_test_operators_mod", None)


@pytest.fixture
def menus_module(fake_bpy):
    module = _load_module("_test_menus_mod", "menus.py", fake_bpy)
    yield module
    sys.modules.pop("_test_menus_mod", None)


# ---------------------------------------------------------------------------
# Mock node-tree data model (just enough for tag/save/auto_layout)
# ---------------------------------------------------------------------------

class MockInterfaceItem:
    def __init__(self, name, in_out, identifier=None,
                 socket_type="NodeSocketGeometry", default_value=None):
        self.name = name
        self.in_out = in_out
        self.identifier = identifier or name
        self.socket_type = socket_type
        self.default_value = default_value


class MockNode:
    def __init__(self, name, bl_idname="GeometryNodeGroup", select=False):
        self.name = name
        self.bl_idname = bl_idname
        self.type = "GROUP" if bl_idname == "GeometryNodeGroup" else bl_idname
        self.node_tree = None
        self.select = select


class MockTree:
    def __init__(self, name, bl_idname="GeometryNodeTree", tagged=False,
                 with_interface=True):
        self.name = name
        self.bl_idname = bl_idname
        self.nodes = []
        self.links = []
        items = []
        if with_interface:
            items = [
                MockInterfaceItem("Geometry", "INPUT", socket_type="NodeSocketGeometry"),
                MockInterfaceItem("Geometry", "OUTPUT", socket_type="NodeSocketGeometry"),
            ]
        self.interface = SimpleNamespace(items_tree=items)
        self._props = {}
        if tagged:
            self._props["synthgen_asset"] = name

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value

    def get(self, key, default=None):
        return self._props.get(key, default)


def _make_context(tree=None, area_type='NODE_EDITOR', path_len=2):
    return SimpleNamespace(
        area=SimpleNamespace(type=area_type),
        space_data=SimpleNamespace(edit_tree=tree, path=list(range(path_len))),
        window_manager=mock.MagicMock(),
        scene=mock.MagicMock(),
        active_object=None,
    )


# ---------------------------------------------------------------------------
# SYNTHGEN_OT_tag_asset
# ---------------------------------------------------------------------------

class TestTagAssetOperator:
    def test_poll_true_inside_group(self, operators_module):
        tree = MockTree("MyGroup")
        ctx = _make_context(tree, path_len=2)
        assert operators_module.SYNTHGEN_OT_tag_asset.poll(ctx) is True

    def test_poll_false_outside_node_editor(self, operators_module):
        tree = MockTree("MyGroup")
        ctx = _make_context(tree, area_type='VIEW_3D', path_len=2)
        assert operators_module.SYNTHGEN_OT_tag_asset.poll(ctx) is False

    def test_poll_false_no_edit_tree(self, operators_module):
        ctx = _make_context(None, path_len=2)
        assert operators_module.SYNTHGEN_OT_tag_asset.poll(ctx) is False

    def test_poll_false_not_geometry_node_tree(self, operators_module):
        tree = MockTree("MyGroup", bl_idname="ShaderNodeTree")
        ctx = _make_context(tree, path_len=2)
        assert operators_module.SYNTHGEN_OT_tag_asset.poll(ctx) is False

    def test_poll_false_top_level_tree(self, operators_module):
        """Editing the top-level modifier tree (path length 1) should not poll."""
        tree = MockTree("MyGroup")
        ctx = _make_context(tree, path_len=1)
        assert operators_module.SYNTHGEN_OT_tag_asset.poll(ctx) is False

    def test_execute_prefixes_and_tags(self, operators_module):
        tree = MockTree("Scatter Points")
        ctx = _make_context(tree)
        op = operators_module.SYNTHGEN_OT_tag_asset()
        result = op.execute(ctx)
        assert result == {'FINISHED'}
        assert tree.name == "SynthGen.Scatter Points"
        assert tree.get("synthgen_asset") == "SynthGen.Scatter Points"
        assert ({'INFO'}, "Tagged 'SynthGen.Scatter Points' as SynthGen asset") in op.reports_log

    def test_execute_does_not_double_prefix(self, operators_module):
        tree = MockTree("SynthGen.Scatter Points")
        ctx = _make_context(tree)
        op = operators_module.SYNTHGEN_OT_tag_asset()
        op.execute(ctx)
        assert tree.name == "SynthGen.Scatter Points"
        assert tree.get("synthgen_asset") == "SynthGen.Scatter Points"

    def test_execute_already_tagged_is_noop(self, operators_module):
        tree = MockTree("SynthGen.Scatter Points", tagged=True)
        ctx = _make_context(tree)
        op = operators_module.SYNTHGEN_OT_tag_asset()
        result = op.execute(ctx)
        assert result == {'FINISHED'}
        assert tree.name == "SynthGen.Scatter Points"
        assert any("already tagged" in msg for _, msg in op.reports_log)


# ---------------------------------------------------------------------------
# SYNTHGEN_OT_save_asset
# ---------------------------------------------------------------------------

class TestSaveAssetOperator:
    def test_poll_true_when_tagged(self, operators_module):
        tree = MockTree("SynthGen.Foo", tagged=True)
        ctx = _make_context(tree)
        assert operators_module.SYNTHGEN_OT_save_asset.poll(ctx) is True

    def test_poll_false_when_untagged(self, operators_module):
        tree = MockTree("SynthGen.Foo", tagged=False)
        ctx = _make_context(tree)
        assert operators_module.SYNTHGEN_OT_save_asset.poll(ctx) is False

    def test_poll_false_outside_node_editor(self, operators_module):
        tree = MockTree("SynthGen.Foo", tagged=True)
        ctx = _make_context(tree, area_type='VIEW_3D')
        assert operators_module.SYNTHGEN_OT_save_asset.poll(ctx) is False

    def test_invoke_prefills_asset_name(self, operators_module):
        tree = MockTree("SynthGen.Foo", tagged=True)
        ctx = _make_context(tree)
        op = operators_module.SYNTHGEN_OT_save_asset()
        op.invoke(ctx, None)
        assert op.asset_name == "SynthGen.Foo"
        ctx.window_manager.invoke_props_dialog.assert_called_once_with(op)

    def test_execute_empty_name_cancels(self, operators_module):
        tree = MockTree("SynthGen.Foo", tagged=True)
        ctx = _make_context(tree)
        op = operators_module.SYNTHGEN_OT_save_asset()
        op.asset_name = "   "
        op.category = "Utility"
        result = op.execute(ctx)
        assert result == {'CANCELLED'}
        assert any(level == {'ERROR'} for level, _ in op.reports_log)

    def _prepped_op(self, operators_module, tmp_path, monkeypatch,
                     tree_name="SynthGen.Foo", asset_name=None,
                     subprocess_result=None, save_calls=None):
        tree = MockTree(tree_name, tagged=True)
        ctx = _make_context(tree)
        op = operators_module.SYNTHGEN_OT_save_asset()
        op.asset_name = asset_name if asset_name is not None else tree_name
        op.category = "Utility"

        monkeypatch.setattr(operators_module, "_assets_dir", str(tmp_path))

        if save_calls is None:
            save_calls = []
        ctx_ops_save = mock.Mock(
            side_effect=lambda **kw: save_calls.append(kw))
        operators_module.bpy.ops.wm.save_as_mainfile = ctx_ops_save

        if subprocess_result is None:
            subprocess_result = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        run_mock = mock.Mock(return_value=subprocess_result)
        monkeypatch.setattr(operators_module.subprocess, "run", run_mock)

        return tree, ctx, op, save_calls, run_mock

    def test_execute_renames_tree_when_user_changed_name(
            self, operators_module, tmp_path, monkeypatch):
        tree, ctx, op, _, _ = self._prepped_op(
            operators_module, tmp_path, monkeypatch,
            tree_name="SynthGen.Foo", asset_name="Bar")
        op.execute(ctx)
        assert tree.name == "SynthGen.Bar"
        assert tree.get("synthgen_asset") == "SynthGen.Bar"

    def test_execute_auto_prefixes_new_name(
            self, operators_module, tmp_path, monkeypatch):
        tree, ctx, op, _, _ = self._prepped_op(
            operators_module, tmp_path, monkeypatch,
            tree_name="SynthGen.Foo", asset_name="Baz")
        op.execute(ctx)
        assert tree.name.startswith("SynthGen.")

    def test_execute_uses_temp_file_not_saved_blend(
            self, operators_module, tmp_path, monkeypatch):
        import tempfile
        tree, ctx, op, save_calls, _ = self._prepped_op(
            operators_module, tmp_path, monkeypatch)
        op.execute(ctx)
        assert len(save_calls) == 1
        filepath = save_calls[0]["filepath"]
        assert save_calls[0]["copy"] is True
        assert os.path.dirname(filepath) == tempfile.gettempdir()

    def test_execute_subprocess_command_has_correct_args(
            self, operators_module, tmp_path, monkeypatch):
        tree, ctx, op, _, run_mock = self._prepped_op(
            operators_module, tmp_path, monkeypatch, tree_name="SynthGen.Foo")
        op.execute(ctx)
        cmd = run_mock.call_args.args[0]
        assert "--tree" in cmd
        assert cmd[cmd.index("--tree") + 1] == "SynthGen.Foo"
        assert "--output" in cmd
        out_path = cmd[cmd.index("--output") + 1]
        assert out_path == os.path.join(str(tmp_path), "foo.blend")
        assert "--catalog-id" in cmd
        cat_uuid = cmd[cmd.index("--catalog-id") + 1]
        from synthgen.assets import CATEGORY_CATALOG
        assert cat_uuid == CATEGORY_CATALOG["Utility"][0]

    def test_execute_generates_manifest_when_missing(
            self, operators_module, tmp_path, monkeypatch):
        tree, ctx, op, _, _ = self._prepped_op(
            operators_module, tmp_path, monkeypatch, tree_name="SynthGen.Foo")
        op.execute(ctx)
        md_path = tmp_path / "foo.md"
        assert md_path.is_file()
        assert any("Generated manifest" in msg for _, msg in op.reports_log)

    def test_execute_does_not_overwrite_existing_manifest(
            self, operators_module, tmp_path, monkeypatch):
        md_path = tmp_path / "foo.md"
        md_path.write_text("# existing manifest\n", encoding="utf-8")
        tree, ctx, op, _, _ = self._prepped_op(
            operators_module, tmp_path, monkeypatch, tree_name="SynthGen.Foo")
        op.execute(ctx)
        assert md_path.read_text(encoding="utf-8") == "# existing manifest\n"
        assert any("not overwritten" in msg for _, msg in op.reports_log)

    def test_execute_reports_error_on_export_failure(
            self, operators_module, tmp_path, monkeypatch):
        failure = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        tree, ctx, op, _, _ = self._prepped_op(
            operators_module, tmp_path, monkeypatch,
            tree_name="SynthGen.Foo", subprocess_result=failure)
        result = op.execute(ctx)
        assert result == {'CANCELLED'}
        assert any("Export failed" in msg for _, msg in op.reports_log)

    def test_execute_blender_not_found(
            self, operators_module, tmp_path, monkeypatch):
        tree = MockTree("SynthGen.Foo", tagged=True)
        ctx = _make_context(tree)
        op = operators_module.SYNTHGEN_OT_save_asset()
        op.asset_name = "SynthGen.Foo"
        op.category = "Utility"
        monkeypatch.setattr(operators_module, "_assets_dir", str(tmp_path))
        operators_module.bpy.ops.wm.save_as_mainfile = mock.Mock()
        monkeypatch.setattr(
            operators_module.subprocess, "run",
            mock.Mock(side_effect=FileNotFoundError()))
        result = op.execute(ctx)
        assert result == {'CANCELLED'}
        assert any("Blender not found" in msg for _, msg in op.reports_log)

    def test_execute_timeout(self, operators_module, tmp_path, monkeypatch):
        tree = MockTree("SynthGen.Foo", tagged=True)
        ctx = _make_context(tree)
        op = operators_module.SYNTHGEN_OT_save_asset()
        op.asset_name = "SynthGen.Foo"
        op.category = "Utility"
        monkeypatch.setattr(operators_module, "_assets_dir", str(tmp_path))
        operators_module.bpy.ops.wm.save_as_mainfile = mock.Mock()
        monkeypatch.setattr(
            operators_module.subprocess, "run",
            mock.Mock(side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60)))
        result = op.execute(ctx)
        assert result == {'CANCELLED'}
        assert any("timed out" in msg for _, msg in op.reports_log)


# ---------------------------------------------------------------------------
# SYNTHGEN_OT_auto_layout
# ---------------------------------------------------------------------------

class TestAutoLayoutOperator:
    def test_poll_true_with_edit_tree(self, operators_module):
        tree = MockTree("Any")
        ctx = _make_context(tree)
        assert operators_module.SYNTHGEN_OT_auto_layout.poll(ctx) is True

    def test_poll_false_without_edit_tree(self, operators_module):
        ctx = _make_context(None)
        assert operators_module.SYNTHGEN_OT_auto_layout.poll(ctx) is False

    def test_poll_false_outside_node_editor(self, operators_module):
        tree = MockTree("Any")
        ctx = _make_context(tree, area_type='VIEW_3D')
        assert operators_module.SYNTHGEN_OT_auto_layout.poll(ctx) is False

    def test_execute_no_selection_passes_none(self, operators_module, monkeypatch):
        import synthgen.layout as layout_mod
        tree = MockTree("Any")
        tree.nodes = [MockNode("A", select=False), MockNode("B", select=False)]
        ctx = _make_context(tree)
        mock_auto_layout = mock.Mock()
        monkeypatch.setattr(layout_mod, "auto_layout", mock_auto_layout)

        op = operators_module.SYNTHGEN_OT_auto_layout()
        result = op.execute(ctx)

        assert result == {'FINISHED'}
        mock_auto_layout.assert_called_once_with(tree)
        assert any("Laid out 2 nodes" in msg for _, msg in op.reports_log)

    def test_execute_selection_passes_selected_subset(self, operators_module, monkeypatch):
        import synthgen.layout as layout_mod
        tree = MockTree("Any")
        a = MockNode("A", select=True)
        b = MockNode("B", select=False)
        c = MockNode("C", select=True)
        tree.nodes = [a, b, c]
        ctx = _make_context(tree)
        mock_auto_layout = mock.Mock()
        monkeypatch.setattr(layout_mod, "auto_layout", mock_auto_layout)

        op = operators_module.SYNTHGEN_OT_auto_layout()
        result = op.execute(ctx)

        assert result == {'FINISHED'}
        mock_auto_layout.assert_called_once_with(tree, nodes=[a, c])
        assert any("Laid out 2 selected nodes" in msg for _, msg in op.reports_log)


# ---------------------------------------------------------------------------
# Menu registration
# ---------------------------------------------------------------------------

class TestMenus:
    def test_asset_menu_idname_and_label(self, menus_module):
        assert menus_module.NODE_MT_synthgen_asset.bl_idname == "NODE_MT_synthgen_asset"
        assert menus_module.NODE_MT_synthgen_asset.bl_label == "Asset"

    def test_layout_menu_idname_and_label(self, menus_module):
        assert menus_module.NODE_MT_synthgen_layout.bl_idname == "NODE_MT_synthgen_layout"
        assert menus_module.NODE_MT_synthgen_layout.bl_label == "Layout"

    def test_top_level_menu_idname_and_label(self, menus_module):
        assert menus_module.NODE_MT_synthgen.bl_idname == "NODE_MT_synthgen"
        assert menus_module.NODE_MT_synthgen.bl_label == "SynthGen"

    def test_asset_menu_draws_tag_and_save_operators(self, menus_module):
        menu = menus_module.NODE_MT_synthgen_asset()
        menu.draw(None)
        calls = [c.args[0] for c in menu.layout.operator.call_args_list]
        assert "synthgen.tag_asset" in calls
        assert "synthgen.save_asset" in calls

    def test_layout_menu_draws_auto_layout_operator(self, menus_module):
        menu = menus_module.NODE_MT_synthgen_layout()
        menu.draw(None)
        calls = [c.args[0] for c in menu.layout.operator.call_args_list]
        assert "synthgen.auto_layout" in calls

    def test_register_registers_all_classes_and_appends_menus(self, menus_module):
        bpy = menus_module.bpy
        menus_module.register()
        registered = [c.args[0] for c in bpy.utils.register_class.call_args_list]
        assert registered == menus_module._classes
        bpy.types.NODE_MT_editor_menus.append.assert_called_once_with(
            menus_module._draw_header_menu)
        bpy.types.NODE_MT_context_menu.append.assert_called_once_with(
            menus_module._draw_context_menu)

    def test_unregister_removes_menus_and_unregisters_classes_reversed(self, menus_module):
        bpy = menus_module.bpy
        menus_module.unregister()
        bpy.types.NODE_MT_context_menu.remove.assert_called_once_with(
            menus_module._draw_context_menu)
        bpy.types.NODE_MT_editor_menus.remove.assert_called_once_with(
            menus_module._draw_header_menu)
        unregistered = [c.args[0] for c in bpy.utils.unregister_class.call_args_list]
        assert unregistered == list(reversed(menus_module._classes))


# ---------------------------------------------------------------------------
# Export worker: keep_groups closure logic (extracted, pure-Python)
# ---------------------------------------------------------------------------

class WorkerMockNode:
    def __init__(self, node_type, node_tree=None):
        self.type = node_type
        self.node_tree = node_tree


class WorkerMockGroup:
    def __init__(self, name, nodes=None):
        self.name = name
        self.nodes = nodes or []


@pytest.fixture
def worker_module():
    fake_bpy = mock.MagicMock(name="bpy")
    module = _load_module(
        "_test_export_worker_mod", "_export_asset_worker.py", fake_bpy,
        source_dir=SCRIPTS_DIR)
    yield module
    sys.modules.pop("_test_export_worker_mod", None)


class TestExportWorkerKeepGroups:
    def test_root_only_when_no_subgroups(self, worker_module):
        root = WorkerMockGroup("SynthGen.Root")
        assert worker_module._keep_groups(root) == {"SynthGen.Root"}

    def test_includes_direct_subgroup(self, worker_module):
        sub = WorkerMockGroup("SynthGen.Sub")
        root = WorkerMockGroup(
            "SynthGen.Root", nodes=[WorkerMockNode("GROUP", node_tree=sub)])
        assert worker_module._keep_groups(root) == {"SynthGen.Root", "SynthGen.Sub"}

    def test_includes_transitive_subgroups(self, worker_module):
        leaf = WorkerMockGroup("SynthGen.Leaf")
        mid = WorkerMockGroup(
            "SynthGen.Mid", nodes=[WorkerMockNode("GROUP", node_tree=leaf)])
        root = WorkerMockGroup(
            "SynthGen.Root", nodes=[WorkerMockNode("GROUP", node_tree=mid)])
        result = worker_module._keep_groups(root)
        assert result == {"SynthGen.Root", "SynthGen.Mid", "SynthGen.Leaf"}

    def test_excludes_unrelated_groups(self, worker_module):
        sub = WorkerMockGroup("SynthGen.Sub")
        root = WorkerMockGroup(
            "SynthGen.Root", nodes=[WorkerMockNode("GROUP", node_tree=sub)])
        result = worker_module._keep_groups(root)
        assert "SynthGen.Unrelated" not in result

    def test_ignores_non_group_nodes(self, worker_module):
        root = WorkerMockGroup(
            "SynthGen.Root", nodes=[WorkerMockNode("MESH_BOOLEAN", node_tree=None)])
        assert worker_module._keep_groups(root) == {"SynthGen.Root"}

    def test_handles_cycles_without_infinite_recursion(self, worker_module):
        a = WorkerMockGroup("SynthGen.A")
        b = WorkerMockGroup("SynthGen.B")
        a.nodes = [WorkerMockNode("GROUP", node_tree=b)]
        b.nodes = [WorkerMockNode("GROUP", node_tree=a)]  # cycle back to a
        result = worker_module._keep_groups(a)
        assert result == {"SynthGen.A", "SynthGen.B"}

    def test_diamond_dependency_deduped(self, worker_module):
        shared = WorkerMockGroup("SynthGen.Shared")
        left = WorkerMockGroup(
            "SynthGen.Left", nodes=[WorkerMockNode("GROUP", node_tree=shared)])
        right = WorkerMockGroup(
            "SynthGen.Right", nodes=[WorkerMockNode("GROUP", node_tree=shared)])
        root = WorkerMockGroup("SynthGen.Root", nodes=[
            WorkerMockNode("GROUP", node_tree=left),
            WorkerMockNode("GROUP", node_tree=right),
        ])
        result = worker_module._keep_groups(root)
        assert result == {
            "SynthGen.Root", "SynthGen.Left", "SynthGen.Right", "SynthGen.Shared",
        }
