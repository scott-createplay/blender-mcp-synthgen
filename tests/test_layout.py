"""Offline tests for ``synthgen.layout`` — no Blender required."""

import pytest

from synthgen.layout import auto_layout


# ---------------------------------------------------------------------------
# Minimal mock model (just enough for layout)
# ---------------------------------------------------------------------------

class MockSocket:
    def __init__(self, name):
        self.name = name


class MockNode:
    def __init__(self, name, n_inputs=1, n_outputs=1):
        self.name = name
        self.inputs = [MockSocket(f"in_{i}") for i in range(n_inputs)]
        self.outputs = [MockSocket(f"out_{i}") for i in range(n_outputs)]
        self._loc = (0.0, 0.0)

    @property
    def location(self):
        return self._loc

    @location.setter
    def location(self, value):
        self._loc = tuple(value)


class MockLink:
    def __init__(self, from_node, to_node):
        self.from_node = from_node
        self.to_node = to_node


class MockTree:
    def __init__(self, nodes, links):
        self.nodes = list(nodes)
        self.links = list(links)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(node):
    return node.location


def _make_chain(n):
    """A → B → C → ... linear chain of *n* nodes."""
    nodes = [MockNode(chr(65 + i)) for i in range(n)]
    links = [MockLink(nodes[i], nodes[i + 1]) for i in range(n - 1)]
    return MockTree(nodes, links)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAutoLayout:

    def test_single_node_no_op(self):
        n = MockNode("A")
        tree = MockTree([n], [])
        auto_layout(tree)
        assert _pos(n) == (0.0, 0.0)

    def test_two_node_chain(self):
        a = MockNode("A")
        b = MockNode("B")
        tree = MockTree([a, b], [MockLink(a, b)])
        auto_layout(tree)
        assert _pos(a)[0] < _pos(b)[0], "source should be left of sink"

    def test_linear_chain_column_count(self):
        tree = _make_chain(4)
        auto_layout(tree)
        xs = sorted({_pos(n)[0] for n in tree.nodes})
        assert len(xs) == 4, "4-node chain should produce 4 columns"

    def test_sinks_rightmost(self):
        tree = _make_chain(3)
        auto_layout(tree)
        sink = tree.nodes[-1]
        for n in tree.nodes:
            assert _pos(n)[0] <= _pos(sink)[0]

    def test_sources_leftmost(self):
        tree = _make_chain(3)
        auto_layout(tree)
        source = tree.nodes[0]
        for n in tree.nodes:
            assert _pos(n)[0] >= _pos(source)[0]

    def test_column_spacing(self):
        tree = _make_chain(3)
        auto_layout(tree, x_spacing=500)
        xs = sorted({_pos(n)[0] for n in tree.nodes})
        gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        assert all(g == 500 for g in gaps)

    def test_disconnected_nodes_placed_at_sink_column(self):
        a = MockNode("A")
        b = MockNode("B")
        c = MockNode("C")
        tree = MockTree([a, b, c], [MockLink(a, b)])
        auto_layout(tree)
        assert _pos(c)[0] == _pos(b)[0], "disconnected node at sink layer"

    def test_diamond_graph(self):
        a = MockNode("A")
        b = MockNode("B")
        c = MockNode("C")
        d = MockNode("D")
        links = [MockLink(a, b), MockLink(a, c), MockLink(b, d), MockLink(c, d)]
        tree = MockTree([a, b, c, d], links)
        auto_layout(tree)
        assert _pos(a)[0] < _pos(b)[0]
        assert _pos(a)[0] < _pos(c)[0]
        assert _pos(b)[0] < _pos(d)[0]
        assert _pos(b)[0] == _pos(c)[0], "parallel branches same column"

    def test_vertical_spacing_from_sockets(self):
        a = MockNode("A", n_inputs=5, n_outputs=5)
        b = MockNode("B", n_inputs=1, n_outputs=1)
        tree = MockTree([a, b], [])
        auto_layout(tree)
        ya = _pos(a)[1]
        yb = _pos(b)[1]
        gap = abs(ya - yb)
        assert gap >= 150

    def test_subset_layout(self):
        """When *nodes* is provided, only those nodes move."""
        a = MockNode("A")
        b = MockNode("B")
        c = MockNode("C")
        c.location = (999, 999)
        links = [MockLink(a, b), MockLink(b, c)]
        tree = MockTree([a, b, c], links)
        auto_layout(tree, nodes=[a, b])
        assert _pos(c) == (999, 999), "node outside subset should not move"
        assert _pos(a)[0] < _pos(b)[0]

    def test_subset_ignores_external_links(self):
        """Links to nodes outside the subset don't affect layer assignment."""
        a = MockNode("A")
        b = MockNode("B")
        c = MockNode("C")
        links = [MockLink(a, b), MockLink(b, c)]
        tree = MockTree([a, b, c], links)
        auto_layout(tree, nodes=[a, b])
        assert _pos(b)[0] > _pos(a)[0], "b is sink of the subset"

    def test_empty_tree(self):
        tree = MockTree([], [])
        auto_layout(tree)

    def test_cycle_does_not_hang(self):
        """A cycle in the graph should not cause an infinite loop."""
        a = MockNode("A")
        b = MockNode("B")
        links = [MockLink(a, b), MockLink(b, a)]
        tree = MockTree([a, b], links)
        auto_layout(tree)
