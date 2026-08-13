"""Live bpy backend — lazy, pull-based SceneGraph over the running Blender scene.

REQUIRES BLENDER. The module stays importable without bpy (so the package imports on any
machine), but instantiating LiveGraph without Blender raises. Not covered by the offline test
suite — validate under `blender --background --python ...` or headless `pip install bpy`.

Tier-① (native pointer) edges are queried on demand (Houdini-style cook-on-pull).
Tier-② (attr_bridge) edges are resolved by calling `resolve_attr_bridges()` — cooks the
depsgraph, reads evaluated `.attributes`, joins with shader readers and GN writer provenance.

Addressing (stable qualified paths):
    COL:<col> ; OBJ:<obj> ; OBJ:<obj>/MOD:<mod> ; NG:<tree> ; MAT:<mat> ;
    <container>/NODE:<node>
"""

from __future__ import annotations

from typing import Iterator, Optional

from .protocol import TIER_NATIVE, TIER_RECONSTRUCTED, Edge

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
        self._bridge_edges: dict[str, list[Edge]] = {}

    # --- protocol ---------------------------------------------------------
    def nodes(self) -> Iterator[str]:
        """Bounded top-level enumeration; deeper ids are reached via neighbors().

        After resolve_attr_bridges(), also yields bridge-participating NODE: ids
        so attribute_trace / impact_set can discover tier-2 edges.
        """
        yield _col(self.scene.collection)
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
        for nid in self._bridge_edges:
            yield nid

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
        yield from self._bridge_edges.get(node_id, ())

    def _collection(self, cid):
        name = cid[4:]
        if name == self.scene.collection.name:
            c = self.scene.collection
        else:
            c = bpy.data.collections.get(name)
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
        yield from self._drivers(oid, o)

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

    def _drivers(self, oid, obj):
        ad = obj.animation_data
        if not ad:
            return
        seen = set()
        for fc in ad.drivers:
            for var in fc.driver.variables:
                for target in var.targets:
                    ref = target.id
                    if ref is None or not isinstance(ref, bpy.types.Object):
                        continue
                    ref_id = _obj(ref)
                    if ref_id not in seen:
                        seen.add(ref_id)
                        yield _e(ref_id, oid, "drives")

    # --- tier-2: attribute bridge -------------------------------------------

    def resolve_attr_bridges(self):
        """Cook the depsgraph and resolve GN↔shader attribute bridge edges.

        Joins three sources (see knowledge/attribute_bridge.md):
          1. Evaluated .attributes on each object (authoritative names)
          2. ShaderNodeAttribute.attribute_name on each material (readers)
          3. GN Store Named Attribute nodes (provenance — best-effort if name is dynamic)

        Call explicitly; populates self._bridge_edges so neighbors() yields them.
        """
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        self._bridge_edges = {}

        for obj in bpy.data.objects:
            gn_trees = []
            for mod in obj.modifiers:
                if mod.type == "NODES" and mod.node_group:
                    gn_trees.append(mod.node_group)
            if not gn_trees:
                continue

            materials = [
                slot.material for slot in obj.material_slots
                if slot.material and slot.material.use_nodes and slot.material.node_tree
            ]
            if not materials:
                continue

            shader_readers = {}
            for mat in materials:
                for node in mat.node_tree.nodes:
                    if node.bl_idname == "ShaderNodeAttribute" and node.attribute_name:
                        nid = f"{_mat(mat)}/NODE:{node.name}"
                        shader_readers.setdefault(node.attribute_name, []).append(nid)

            if not shader_readers:
                continue

            eval_obj = obj.evaluated_get(dg)
            eval_attrs = {}
            if eval_obj.data and hasattr(eval_obj.data, "attributes"):
                for a in eval_obj.data.attributes:
                    eval_attrs[a.name] = {
                        "domain": a.domain,
                        "data_type": a.data_type,
                    }
            if hasattr(eval_obj, "evaluated_geometry"):
                try:
                    geom = eval_obj.evaluated_geometry()
                    ipc = geom.instances_pointcloud() if geom else None
                    if ipc and hasattr(ipc, "attributes"):
                        for a in ipc.attributes:
                            if a.name not in eval_attrs:
                                eval_attrs[a.name] = {
                                    "domain": a.domain,
                                    "data_type": a.data_type,
                                }
                except Exception:
                    pass

            gn_writers = {}
            for tree in gn_trees:
                for node in tree.nodes:
                    if node.bl_idname == "GeometryNodeStoreNamedAttribute":
                        name_sock = node.inputs.get("Name")
                        if name_sock and not name_sock.is_linked:
                            attr_name = name_sock.default_value
                            if attr_name:
                                nid = f"{_ng(tree)}/NODE:{node.name}"
                                gn_writers.setdefault(attr_name, []).append({
                                    "node_id": nid,
                                    "data_type": node.data_type,
                                    "domain": node.domain,
                                })

            bridged = set(shader_readers.keys()) & (
                set(eval_attrs.keys()) | set(gn_writers.keys())
            )

            for attr_name in bridged:
                writers = gn_writers.get(attr_name, [])
                readers = shader_readers[attr_name]
                confirmed = attr_name in eval_attrs

                for reader_id in readers:
                    if writers:
                        for w in writers:
                            edge = Edge(
                                src=reader_id, dst=w["node_id"],
                                type="attr_bridge",
                                tier=TIER_RECONSTRUCTED,
                                state_dependent=True,
                                data={
                                    "attr": attr_name,
                                    "domain": w["domain"],
                                    "data_type": w["data_type"],
                                    "object": _obj(obj),
                                    "confirmed_by_eval": confirmed,
                                },
                            )
                            self._bridge_edges.setdefault(reader_id, []).append(edge)
                    else:
                        ea = eval_attrs.get(attr_name, {})
                        edge = Edge(
                            src=reader_id, dst=_obj(obj),
                            type="attr_bridge",
                            tier=TIER_RECONSTRUCTED,
                            state_dependent=True,
                            resolved=False,
                            data={
                                "attr": attr_name,
                                "domain": ea.get("domain", "UNKNOWN"),
                                "data_type": ea.get("data_type", "UNKNOWN"),
                                "object": _obj(obj),
                                "confirmed_by_eval": confirmed,
                                "note": "writer unresolved — name may be dynamic",
                            },
                        )
                        self._bridge_edges.setdefault(reader_id, []).append(edge)
