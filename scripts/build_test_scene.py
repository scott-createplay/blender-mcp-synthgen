"""
build_test_scene.py  --  Build a Blender 5.x test scene for scene-graph walker validation.

Run headless (from the project root):
    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" -b -P scripts/build_test_scene.py

Produces:
    scenes/test_scene.blend   -- the scene file
    scenes/ground_truth.json  -- machine-readable manifest of every node, edge, and attribute

Feature-coverage matrix (13 features):
    1. Object hierarchy (parent/child)
    2. Collection hierarchy (nested)
    3. GN modifier on an object
    4. Node group with internal links
    5. Group input exposing a parameter
    6. Material slot -> material
    7. Shader node tree with links
    8. ShaderNodeAttribute reading a named attribute
    9. GN Store Named Attribute
   10. Instance on Points
   11. Compositor node group (5.x path)
   12. Driver on a value
   13. Object reference in GN modifier
"""

import bpy
import json
import os
import sys


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
SCENES_DIR = os.path.join(PROJECT_DIR, "scenes")
BLEND_PATH = os.path.join(SCENES_DIR, "test_scene.blend")
MANIFEST_PATH = os.path.join(SCENES_DIR, "ground_truth.json")

os.makedirs(SCENES_DIR, exist_ok=True)

print(f"[build] Project root : {PROJECT_DIR}")
print(f"[build] Output dir   : {SCENES_DIR}")


# ---------------------------------------------------------------------------
# 1. Purge defaults
# ---------------------------------------------------------------------------
print("[build] Purging default scene data ...")

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for mesh in list(bpy.data.meshes):
    bpy.data.meshes.remove(mesh)
for mat in list(bpy.data.materials):
    bpy.data.materials.remove(mat)
for col in list(bpy.data.collections):
    bpy.data.collections.remove(col)
for ng in list(bpy.data.node_groups):
    bpy.data.node_groups.remove(ng)
for cam in list(bpy.data.cameras):
    bpy.data.cameras.remove(cam)
for light in list(bpy.data.lights):
    bpy.data.lights.remove(light)

scene = bpy.context.scene
print(f"[build] Scene collection name: {scene.collection.name!r}")


# ---------------------------------------------------------------------------
# 2. Collection hierarchy  (features 2)
# ---------------------------------------------------------------------------
print("[build] Creating collection hierarchy ...")

root_col = bpy.data.collections.new("TestRoot")
scene.collection.children.link(root_col)

child_col = bpy.data.collections.new("ChildCollection")
root_col.children.link(child_col)

print(f"  Scene Collection -> {root_col.name} -> {child_col.name}")


# ---------------------------------------------------------------------------
# 3. Objects  (features 1, 10, 12, 13)
# ---------------------------------------------------------------------------
print("[build] Creating objects ...")

# -- ParentEmpty --
parent_empty = bpy.data.objects.new("ParentEmpty", None)
parent_empty.empty_display_type = "PLAIN_AXES"
root_col.objects.link(parent_empty)

# -- ChildCube  (will receive GN modifier + material + driver) --
cube_mesh = bpy.data.meshes.new("ChildCube_Mesh")
verts = [
    (-1, -1, -1), ( 1, -1, -1), ( 1,  1, -1), (-1,  1, -1),
    (-1, -1,  1), ( 1, -1,  1), ( 1,  1,  1), (-1,  1,  1),
]
faces = [
    (0, 1, 2, 3), (4, 5, 6, 7),
    (0, 1, 5, 4), (2, 3, 7, 6),
    (0, 3, 7, 4), (1, 2, 6, 5),
]
cube_mesh.from_pydata(verts, [], faces)
cube_mesh.update()
child_cube = bpy.data.objects.new("ChildCube", cube_mesh)
child_col.objects.link(child_cube)
child_cube.parent = parent_empty          # feature 1: parent/child

# -- InstanceTarget  (small tetrahedron used as instance template) --
target_mesh = bpy.data.meshes.new("InstanceTarget_Mesh")
tv = [
    ( 0.0,   0.0,   0.2),
    ( 0.2,   0.0,  -0.1),
    (-0.1,   0.17, -0.1),
    (-0.1,  -0.17, -0.1),
]
tf = [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)]
target_mesh.from_pydata(tv, [], tf)
target_mesh.update()
instance_target = bpy.data.objects.new("InstanceTarget", target_mesh)
child_col.objects.link(instance_target)

# -- DriverSource  (empty whose location.y drives ChildCube.location.x) --
driver_source = bpy.data.objects.new("DriverSource", None)
driver_source.empty_display_type = "ARROWS"
driver_source.location = (0, 3, 0)
root_col.objects.link(driver_source)

print(f"  Objects: {[o.name for o in bpy.data.objects]}")


# ---------------------------------------------------------------------------
# 4. Material + shader nodes  (features 6, 7, 8)
# ---------------------------------------------------------------------------
print("[build] Creating material with shader nodes ...")

mat = bpy.data.materials.new("TestMaterial")
mat.use_nodes = True
mat_tree = mat.node_tree

# Clear auto-created nodes
for node in list(mat_tree.nodes):
    mat_tree.nodes.remove(node)

# Material Output
mat_output = mat_tree.nodes.new("ShaderNodeOutputMaterial")
mat_output.name = "Material Output"
mat_output.location = (400, 0)

# Principled BSDF
principled = mat_tree.nodes.new("ShaderNodeBsdfPrincipled")
principled.name = "Principled BSDF"
principled.location = (100, 0)

# Attribute node -- reads "inst_color" written by GN  (feature 8)
attr_node = mat_tree.nodes.new("ShaderNodeAttribute")
attr_node.name = "Attribute"
attr_node.attribute_name = "inst_color"
attr_node.attribute_type = "INSTANCER"
attr_node.location = (-200, 0)

# Links  (feature 7)
mat_tree.links.new(attr_node.outputs["Color"], principled.inputs["Base Color"])
mat_tree.links.new(principled.outputs["BSDF"], mat_output.inputs["Surface"])

# Assign material to ChildCube  (feature 6)
child_cube.data.materials.append(mat)

print(f"  Material: {mat.name!r}  nodes: {[n.name for n in mat_tree.nodes]}")
print(f"  Material links: {len(mat_tree.links)}")


# ---------------------------------------------------------------------------
# 5. Geometry Nodes tree + modifier  (features 3, 4, 5, 9, 10, 13)
# ---------------------------------------------------------------------------
print("[build] Building Geometry Nodes tree ...")

gn_tree = bpy.data.node_groups.new("GN_TestTree", "GeometryNodeTree")

# -- Interface sockets  (feature 5: group input exposing a parameter) --
gn_tree.interface.new_socket(
    name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
)
gn_tree.interface.new_socket(
    name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
)
gn_tree.interface.new_socket(
    name="Density", in_out="INPUT", socket_type="NodeSocketFloat"
)
print("  Interface sockets created (Geometry in/out, Density float)")

# -- Nodes --
group_in = gn_tree.nodes.new("NodeGroupInput")
group_in.name = "Group Input"
group_in.location = (-800, 0)

group_out = gn_tree.nodes.new("NodeGroupOutput")
group_out.name = "Group Output"
group_out.location = (600, 0)

# Store Named Attribute  (feature 9)
# IMPORTANT: set data_type BEFORE linking Value socket
store_attr = gn_tree.nodes.new("GeometryNodeStoreNamedAttribute")
store_attr.name = "Store Named Attribute"
store_attr.data_type = "FLOAT_COLOR"
store_attr.domain = "POINT"
store_attr.location = (-200, 0)
store_attr.inputs["Name"].default_value = "inst_color"

# Random Value -- generates per-point random color
random_val = gn_tree.nodes.new("FunctionNodeRandomValue")
random_val.name = "Random Value"
random_val.data_type = "FLOAT_VECTOR"   # closest to color; Blender auto-converts
random_val.location = (-500, -200)

# Instance on Points  (feature 10)
instance_on_pts = gn_tree.nodes.new("GeometryNodeInstanceOnPoints")
instance_on_pts.name = "Instance on Points"
instance_on_pts.location = (200, 0)

# Object Info  (feature 13: references InstanceTarget)
obj_info = gn_tree.nodes.new("GeometryNodeObjectInfo")
obj_info.name = "Object Info"
obj_info.location = (0, -300)
obj_info.inputs["Object"].default_value = instance_target

# -- Internal links  (feature 4) --
# Group Input.Geometry -> Store Named Attribute.Geometry
gn_tree.links.new(group_in.outputs["Geometry"], store_attr.inputs["Geometry"])
# Random Value.Value -> Store Named Attribute.Value  (color data via vector)
gn_tree.links.new(random_val.outputs["Value"], store_attr.inputs["Value"])
# Store Named Attribute.Geometry -> Instance on Points.Points
gn_tree.links.new(store_attr.outputs["Geometry"], instance_on_pts.inputs["Points"])
# Object Info.Geometry -> Instance on Points.Instance
gn_tree.links.new(obj_info.outputs["Geometry"], instance_on_pts.inputs["Instance"])
# Instance on Points.Instances -> Group Output.Geometry
gn_tree.links.new(instance_on_pts.outputs["Instances"], group_out.inputs["Geometry"])

print(f"  GN tree: {gn_tree.name!r}  nodes: {[n.name for n in gn_tree.nodes]}")
print(f"  GN links: {len(gn_tree.links)}")

# -- Apply GN modifier to ChildCube  (feature 3) --
gn_mod = child_cube.modifiers.new(name="GeometryNodes", type="NODES")
gn_mod.node_group = gn_tree
print(f"  Modifier: {gn_mod.name!r} on {child_cube.name!r}")


# ---------------------------------------------------------------------------
# 6. Compositor  (feature 11 -- 5.x path via compositing_node_group)
# ---------------------------------------------------------------------------
print("[build] Setting up compositor (5.x compositing_node_group) ...")

scene.use_nodes = True
comp_tree = scene.compositing_node_group

if comp_tree is None:
    comp_tree = bpy.data.node_groups.new("CompositorTree", "CompositorNodeTree")
    scene.compositing_node_group = comp_tree
    print("  Created new compositor node group")
else:
    comp_tree.name = "CompositorTree"
    print(f"  Using auto-created compositor node group, renamed to {comp_tree.name!r}")

# Clear any auto-created nodes
for node in list(comp_tree.nodes):
    comp_tree.nodes.remove(node)

# Render Layers
rl_node = comp_tree.nodes.new("CompositorNodeRLayers")
rl_node.name = "Render Layers"
rl_node.location = (-300, 0)

# Brightness/Contrast  (the "extra node")
bc_node = comp_tree.nodes.new("CompositorNodeBrightContrast")
bc_node.name = "Brightness/Contrast"
bc_node.location = (0, 0)

# Viewer  (5.x output: CompositorNodeComposite does not exist in node groups)
viewer_node = comp_tree.nodes.new("CompositorNodeViewer")
viewer_node.name = "Viewer"
viewer_node.location = (300, 0)

# Links: Render Layers -> Brightness/Contrast -> Viewer
comp_tree.links.new(rl_node.outputs["Image"], bc_node.inputs["Image"])
comp_tree.links.new(bc_node.outputs["Image"], viewer_node.inputs["Image"])

print(f"  Compositor tree: {comp_tree.name!r}  nodes: {[n.name for n in comp_tree.nodes]}")
print(f"  Compositor links: {len(comp_tree.links)}")


# ---------------------------------------------------------------------------
# 7. Driver  (feature 12: ChildCube.location.x driven by DriverSource.location.y)
# ---------------------------------------------------------------------------
print("[build] Adding driver ...")

fcurve = child_cube.driver_add("location", 0)   # X component
driver = fcurve.driver
driver.type = "AVERAGE"

var = driver.variables.new()
var.name = "src_y"
var.targets[0].id = driver_source
var.targets[0].data_path = "location[1]"         # Y component

print(f"  Driver: {child_cube.name}.location[0] <- {driver_source.name}.location[1]")


# ---------------------------------------------------------------------------
# 8. Save .blend
# ---------------------------------------------------------------------------
print(f"[build] Saving {BLEND_PATH} ...")
bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
print("[build] .blend saved.")


# ---------------------------------------------------------------------------
# 9. Verification pass -- read back actual names to ensure manifest accuracy
# ---------------------------------------------------------------------------
print("[build] Verification pass ...")

def _check(label, condition, detail=""):
    status = "OK" if condition else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return condition

all_ok = True
all_ok &= _check("Scene collection exists", scene.collection is not None, scene.collection.name)
all_ok &= _check("TestRoot in scene", root_col.name in [c.name for c in scene.collection.children])
all_ok &= _check("ChildCollection in TestRoot", child_col.name in [c.name for c in root_col.children])
all_ok &= _check("ParentEmpty in TestRoot", parent_empty.name in [o.name for o in root_col.objects])
all_ok &= _check("ChildCube in ChildCollection", child_cube.name in [o.name for o in child_col.objects])
all_ok &= _check("ChildCube.parent == ParentEmpty", child_cube.parent == parent_empty)
all_ok &= _check("GN modifier on ChildCube", len(child_cube.modifiers) > 0 and child_cube.modifiers[0].type == "NODES")
all_ok &= _check("GN modifier has node group", gn_mod.node_group == gn_tree)
all_ok &= _check("GN tree has 6 nodes", len(gn_tree.nodes) == 6, f"got {len(gn_tree.nodes)}")
all_ok &= _check("GN tree has 5 links", len(gn_tree.links) == 5, f"got {len(gn_tree.links)}")
all_ok &= _check("Object Info references InstanceTarget",
                  obj_info.inputs["Object"].default_value == instance_target)
all_ok &= _check("Material assigned to ChildCube", len(child_cube.data.materials) == 1)
all_ok &= _check("Material has 3 nodes", len(mat_tree.nodes) == 3, f"got {len(mat_tree.nodes)}")
all_ok &= _check("Attribute node reads inst_color", attr_node.attribute_name == "inst_color")
all_ok &= _check("Compositor tree assigned", scene.compositing_node_group == comp_tree)
all_ok &= _check("Compositor has 3 nodes", len(comp_tree.nodes) == 3, f"got {len(comp_tree.nodes)}")
all_ok &= _check("Driver on ChildCube", child_cube.animation_data is not None and len(child_cube.animation_data.drivers) > 0)

if not all_ok:
    print("[build] WARNING: some verifications failed!")
else:
    print("[build] All verifications passed.")


# ---------------------------------------------------------------------------
# 10. Ground-truth manifest
# ---------------------------------------------------------------------------
print("[build] Building ground-truth manifest ...")

manifest = {
    "meta": {
        "blender_version": "{}.{}.{}".format(*bpy.app.version),
        "built_by": "build_test_scene.py",
        "features_covered": [
            "object_hierarchy",
            "collection_hierarchy",
            "gn_modifier",
            "gn_internal_links",
            "group_input_parameter",
            "material_slot",
            "shader_node_tree_links",
            "shader_attribute_reads_named_attr",
            "gn_store_named_attribute",
            "instance_on_points",
            "compositor_node_group_5x",
            "driver",
            "object_reference_in_gn",
        ],
    },
    # ------------------------------------------------------------------
    # NODES — every identifiable entity in the scene
    # ------------------------------------------------------------------
    "nodes": [
        # Collections
        {"id": "COL:{}".format(scene.collection.name), "kind": "collection"},
        {"id": "COL:{}".format(root_col.name), "kind": "collection"},
        {"id": "COL:{}".format(child_col.name), "kind": "collection"},
        # Objects
        {"id": "OBJ:{}".format(parent_empty.name), "kind": "object"},
        {"id": "OBJ:{}".format(child_cube.name), "kind": "object"},
        {"id": "OBJ:{}".format(instance_target.name), "kind": "object"},
        {"id": "OBJ:{}".format(driver_source.name), "kind": "object"},
        # Modifier
        {"id": "OBJ:{}/MOD:{}".format(child_cube.name, gn_mod.name), "kind": "modifier"},
        # Node-tree definitions
        {"id": "NG:{}".format(gn_tree.name), "kind": "nodetree_def"},
        {"id": "NG:{}".format(comp_tree.name), "kind": "nodetree_def"},
        # GN nodes
        {"id": "NG:{}/NODE:{}".format(gn_tree.name, group_in.name), "kind": "gn_node"},
        {"id": "NG:{}/NODE:{}".format(gn_tree.name, group_out.name), "kind": "gn_node"},
        {"id": "NG:{}/NODE:{}".format(gn_tree.name, store_attr.name), "kind": "gn_node"},
        {"id": "NG:{}/NODE:{}".format(gn_tree.name, random_val.name), "kind": "gn_node"},
        {"id": "NG:{}/NODE:{}".format(gn_tree.name, instance_on_pts.name), "kind": "gn_node"},
        {"id": "NG:{}/NODE:{}".format(gn_tree.name, obj_info.name), "kind": "gn_node"},
        # Material
        {"id": "MAT:{}".format(mat.name), "kind": "material"},
        # Material / shader nodes
        {"id": "MAT:{}/NODE:{}".format(mat.name, mat_output.name), "kind": "shader_node"},
        {"id": "MAT:{}/NODE:{}".format(mat.name, principled.name), "kind": "shader_node"},
        {"id": "MAT:{}/NODE:{}".format(mat.name, attr_node.name), "kind": "shader_node"},
        # Compositor nodes
        {"id": "NG:{}/NODE:{}".format(comp_tree.name, rl_node.name), "kind": "compositor_node"},
        {"id": "NG:{}/NODE:{}".format(comp_tree.name, bc_node.name), "kind": "compositor_node"},
        {"id": "NG:{}/NODE:{}".format(comp_tree.name, viewer_node.name), "kind": "compositor_node"},
    ],
    # ------------------------------------------------------------------
    # EDGES — every structural relationship
    # ------------------------------------------------------------------
    "edges": [
        # --- Collection hierarchy ---
        {
            "src": "COL:{}".format(scene.collection.name),
            "dst": "COL:{}".format(root_col.name),
            "type": "collection_contains",
            "tier": 1,
        },
        {
            "src": "COL:{}".format(root_col.name),
            "dst": "COL:{}".format(child_col.name),
            "type": "collection_contains",
            "tier": 1,
        },
        # --- Collection -> object membership ---
        {
            "src": "COL:{}".format(root_col.name),
            "dst": "OBJ:{}".format(parent_empty.name),
            "type": "collection_contains",
            "tier": 1,
        },
        {
            "src": "COL:{}".format(root_col.name),
            "dst": "OBJ:{}".format(driver_source.name),
            "type": "collection_contains",
            "tier": 1,
        },
        {
            "src": "COL:{}".format(child_col.name),
            "dst": "OBJ:{}".format(child_cube.name),
            "type": "collection_contains",
            "tier": 1,
        },
        {
            "src": "COL:{}".format(child_col.name),
            "dst": "OBJ:{}".format(instance_target.name),
            "type": "collection_contains",
            "tier": 1,
        },
        # --- Object parent/child ---
        {
            "src": "OBJ:{}".format(child_cube.name),
            "dst": "OBJ:{}".format(parent_empty.name),
            "type": "parent",
            "tier": 1,
        },
        # --- Modifier ---
        {
            "src": "OBJ:{}".format(child_cube.name),
            "dst": "OBJ:{}/MOD:{}".format(child_cube.name, gn_mod.name),
            "type": "has_modifier",
            "tier": 1,
        },
        {
            "src": "OBJ:{}/MOD:{}".format(child_cube.name, gn_mod.name),
            "dst": "NG:{}".format(gn_tree.name),
            "type": "modifier_uses_tree",
            "tier": 1,
        },
        # --- Material ---
        {
            "src": "OBJ:{}".format(child_cube.name),
            "dst": "MAT:{}".format(mat.name),
            "type": "uses_material",
            "tier": 1,
        },
        # --- GN tree -> nodes ---
        {
            "src": "NG:{}".format(gn_tree.name),
            "dst": "NG:{}/NODE:{}".format(gn_tree.name, group_in.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        {
            "src": "NG:{}".format(gn_tree.name),
            "dst": "NG:{}/NODE:{}".format(gn_tree.name, group_out.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        {
            "src": "NG:{}".format(gn_tree.name),
            "dst": "NG:{}/NODE:{}".format(gn_tree.name, store_attr.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        {
            "src": "NG:{}".format(gn_tree.name),
            "dst": "NG:{}/NODE:{}".format(gn_tree.name, random_val.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        {
            "src": "NG:{}".format(gn_tree.name),
            "dst": "NG:{}/NODE:{}".format(gn_tree.name, instance_on_pts.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        {
            "src": "NG:{}".format(gn_tree.name),
            "dst": "NG:{}/NODE:{}".format(gn_tree.name, obj_info.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        # --- Material tree -> nodes ---
        {
            "src": "MAT:{}".format(mat.name),
            "dst": "MAT:{}/NODE:{}".format(mat.name, mat_output.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        {
            "src": "MAT:{}".format(mat.name),
            "dst": "MAT:{}/NODE:{}".format(mat.name, principled.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        {
            "src": "MAT:{}".format(mat.name),
            "dst": "MAT:{}/NODE:{}".format(mat.name, attr_node.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        # --- Compositor tree -> nodes ---
        {
            "src": "NG:{}".format(comp_tree.name),
            "dst": "NG:{}/NODE:{}".format(comp_tree.name, rl_node.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        {
            "src": "NG:{}".format(comp_tree.name),
            "dst": "NG:{}/NODE:{}".format(comp_tree.name, bc_node.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        {
            "src": "NG:{}".format(comp_tree.name),
            "dst": "NG:{}/NODE:{}".format(comp_tree.name, viewer_node.name),
            "type": "tree_contains_node",
            "tier": 1,
        },
        # --- Object reference from GN node ---
        {
            "src": "NG:{}/NODE:{}".format(gn_tree.name, obj_info.name),
            "dst": "OBJ:{}".format(instance_target.name),
            "type": "references_object",
            "tier": 1,
        },
        # --- Driver ---
        {
            "src": "OBJ:{}".format(driver_source.name),
            "dst": "OBJ:{}".format(child_cube.name),
            "type": "drives",
            "tier": 1,
            "detail": "DriverSource.location[1] -> ChildCube.location[0]",
        },
    ],
    # ------------------------------------------------------------------
    # ATTRIBUTES — the tier-2 attribute bridge
    # ------------------------------------------------------------------
    "attributes": [
        {
            "name": "inst_color",
            "domain": "POINT",
            "data_type": "FLOAT_COLOR",
            "writer": "NG:{}/NODE:{}".format(gn_tree.name, store_attr.name),
            "reader": "MAT:{}/NODE:{}".format(mat.name, attr_node.name),
        }
    ],
}

with open(MANIFEST_PATH, "w") as f:
    json.dump(manifest, f, indent=2)

print(f"[build] Manifest written to {MANIFEST_PATH}")
print(f"[build] Nodes : {len(manifest['nodes'])}")
print(f"[build] Edges : {len(manifest['edges'])}")
print(f"[build] Attrs : {len(manifest['attributes'])}")


# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
print("[build] ---- COMPLETE ----")
print(f"  .blend  : {BLEND_PATH}")
print(f"  manifest: {MANIFEST_PATH}")
