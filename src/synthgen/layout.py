"""Topological auto-layout for Blender node trees.

Sinks (Group Output, nodes with no forward edges) are placed rightmost.
Sources are placed leftmost.  Vertical spacing is estimated from socket count.

This is the canonical implementation shared by the Blender operator, the MCP
``layout_node_tree`` tool, and the inline codegen path.
"""

from __future__ import annotations

from collections import deque


def auto_layout(tree, nodes=None, x_spacing=300, y_min=150, y_per_socket=30):
    """Topological auto-layout for a Blender node tree.

    Parameters
    ----------
    tree : bpy.types.NodeTree
        The node tree whose links determine ordering.
    nodes : sequence of nodes, optional
        If provided, only these nodes are repositioned.  Links between
        nodes outside the subset are ignored.  If *None*, all nodes in
        the tree are laid out.
    x_spacing : int
        Horizontal distance between columns (px).
    y_min : int
        Minimum vertical spacing between nodes (px).
    y_per_socket : int
        Additional vertical spacing per socket (px).
    """
    if nodes is not None:
        work = list(nodes)
    else:
        work = list(tree.nodes)

    if len(work) <= 1:
        return

    name_set = {n.name for n in work}

    fwd = {n.name: set() for n in work}
    back = {n.name: set() for n in work}
    for lnk in tree.links:
        fn = lnk.from_node.name
        tn = lnk.to_node.name
        if fn in name_set and tn in name_set:
            fwd[fn].add(tn)
            back[tn].add(fn)

    sinks = [n.name for n in work if not fwd[n.name]]
    if not sinks:
        sinks = [work[-1].name]

    layer = {}
    q = deque(sinks)
    for s in sinks:
        layer[s] = 0
    max_depth = len(work) - 1
    while q:
        cur = q.popleft()
        for p in back.get(cur, ()):
            nd = layer[cur] + 1
            if nd > max_depth:
                continue
            if p not in layer or layer[p] < nd:
                layer[p] = nd
                q.append(p)

    for n in work:
        if n.name not in layer:
            layer[n.name] = 0

    cols = {}
    for nm, cl in layer.items():
        cols.setdefault(cl, []).append(nm)

    mx = max(cols) if cols else 0
    node_by_name = {n.name: n for n in work}
    for cl, nms in cols.items():
        x = (mx - cl) * x_spacing
        y = 0
        for nm in nms:
            nd = node_by_name.get(nm)
            if nd:
                nd.location = (x, y)
                y -= max(y_min, y_per_socket * (len(nd.inputs) + len(nd.outputs)))
