"""Live bpy backend — lazy, pull-based SceneGraph over the running Blender scene.

REQUIRES BLENDER. The module stays importable without bpy (so the package imports on any
machine), but instantiating LiveGraph without Blender raises. Not covered by the offline test
suite — validate under `blender --background --python ...` or headless `pip install bpy`.

Implements **tier-① (native pointer) edges** by querying bpy on demand — an edge is computed
only when a traversal pulls it (Houdini-style cook-on-pull). Tier-② edges (attr_bridge, via
cook-then-read of evaluated `.attributes`) are the documented next step — see the TODO at the
bottom and knowledge/scene_graph_contexts.md.

Addressing (stable qualified paths):
    COL:<col> ; OBJ:<obj> ; OBJ:<obj>/MOD:<mod> ; NG:<tree> ; MAT:<mat> ;
    <container>/NODE:<node>
"""

from __future__ import annotations

from typing import Iterator, Optional

from .protocol import TIER_NATIVE, Edge

try:
    import bpy
except ImportError:  # importable without Blender; construction fails loudly instead
    bpy = None


def _e(src, dst, type_, **data):
    return Edge(src=src, dst=dst, type=type_, tier=TIER_NATIVE,
               data=data if data else {})


def _obj(o):  return f"OBJ:{o.name}"
def _mod(o, m):  return f"OBJ:{o.name}/MOD:{m.name}"
def _ng(ng):  return f"NG:{ng.name}"
def _mat(m):  return f"MAT:{m.name}"
def _col(c):  return f"COL:{c.name}"


class LiveGraph:
    """Lazy SceneGraph over bpy.data. neighbors() queries Blender on demand."""

    def __init__(self, scene=None):
        if bpy is None:
            raise RuntimeError(
                "backend_bpy requires Blender (bpy). Run under Blender or headless `pip install bpy`.")
        self.scene = scene or bpy.context.scene

    # --- protocol ---------------------------------------------------------
    def nodes(self) -> Iterator[str]:
        """Bounded top-level enumeration; deeper ids are reached via neighbors()."""
        for c in bpy.data.collections:
            yield _col(c)
        for o in bpy.data.objects:
            yield _obj(o)
            for m in o.modifiers:
                if m.type == "NODES":
                    yield _mod(o, m)
        for ng in bpy.data.node_groups:
            yield _ng(ng)
        for m in bpy.data.materials:
            yield _mat(m)

    def resolve(self, node_id: str) -> Optional[dict]:
        tail = node_id.rsplit("/", 1)[-1]
        kind = {"COL": "collection", "OBJ": "object", "MOD": "modifier",
                "NG": "nodetree_def", "MAT": "material", "NODE": "node"}.get(tail.split(":", 1)[0])
        return {"id": node_id, "kind": kind}

    def neighbors(self, node_id: str, edge_types: Optional[set] = None) -> Iterator[Edge]:
        for e in self._all(node_id):
            if edge_types is None or e.type in edge_types:
                yield e

    # --- edge generators (tier-1) ----------------------------------------
    def _all(self, node_id):
        if "/NODE:" in node_id:
            yield from self._node_refs(node_id)
        elif node_id.startswith("COL:"):
            yield from self._collection(node_id)
        elif "/MOD:" in node_id:
            yield from self._modifier(node_id)
        elif node_id.startswith("OBJ:"):
            yield from self._object(node_id)
        elif node_id.startswith("NG:"):
            yield from self._tree(node_id, bpy.data.node_groups.get(node_id[3:]))
        elif node_id.startswith("MAT:"):
            m = bpy.data.materials.get(node_id[4:])
            yield from self._tree(node_id, m.node_tree if m and m.use_nodes else None)

    def _collection(self, cid):
        c = bpy.data.collections.get(cid[4:])
        if not c:
            return
        for o in c.objects:
            yield _e(cid, _obj(o), "collection_contains")
        for child in c.children:
            yield _e(cid, _col(child), "collection_contains")

    def _object(self, oid):
        o = bpy.data.objects.get(oid[4:])
        if not o:
            return
        if o.parent:
            yield _e(oid, _obj(o.parent), "parent")
        if o.instance_collection:
            yield _e(oid, _col(o.instance_collection), "instances_collection")
        for m in o.modifiers:
            if m.type == "NODES":
                yield _e(oid, _mod(o, m), "has_modifier")
        for slot in o.material_slots:
            if slot.material:
                yield _e(oid, _mat(slot.material), "uses_material")

    def _modifier(self, mid):
        oname, mname = mid[4:].split("/MOD:")
        o = bpy.data.objects.get(oname)
        m = o.modifiers.get(mname) if o else None
        if m and m.type == "NODES" and m.node_group:
            yield _e(mid, _ng(m.node_group), "modifier_uses_tree")

    def _tree(self, container_id, tree):
        if not tree:
            return
        for n in tree.nodes:
            yield _e(container_id, f"{container_id}/NODE:{n.name}", "tree_contains_node")

    def _node_refs(self, node_id):
        container_id, nname = node_id.rsplit("/NODE:", 1)
        tree = None
        if container_id.startswith("NG:"):
            tree = bpy.data.node_groups.get(container_id[3:])
        elif container_id.startswith("MAT:"):
            m = bpy.data.materials.get(container_id[4:])
            tree = m.node_tree if m and m.use_nodes else None
        n = tree.nodes.get(nname) if tree else None
        if not n:
            return
        # group nesting
        if getattr(n, "node_tree", None):
            yield _e(node_id, _ng(n.node_tree), "node_uses_group")
        # scene references (Object/Collection Info, Set Material, image, etc.)
        for sock_name, ref_type in (("Object", "references_object"),
                                    ("Collection", "references_collection"),
                                    ("Material", "references_material")):
            sock = n.inputs.get(sock_name) if hasattr(n.inputs, "get") else None
            val = getattr(sock, "default_value", None) if sock else None
            if val is not None:
                dst = {"references_object": _obj, "references_collection": _col,
                       "references_material": _mat}[ref_type](val)
                yield _e(node_id, dst, ref_type,
                         note="check modifier-interface input too (see spec gotcha)")

    # --- TODO: tier-2 --------------------------------------------------------
    # resolve_attr_bridges(): cook the depsgraph, read evaluated obj.data.attributes and
    #   dg.object_instances attributes (authoritative names), join with shader
    #   ShaderNodeAttribute.attribute_name and GN Store/Capture provenance -> attr_bridge
    #   edges tagged state_dependent=True. See knowledge/attribute_bridge.md.
