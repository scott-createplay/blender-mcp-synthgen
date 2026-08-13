"""
validate_attr_bridge.py — Validate tier-2 attr_bridge resolution in LiveGraph.

Run headless against the test scene:
    & "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" ^
        -b scenes/test_scene.blend -P scripts/validate_attr_bridge.py

Exercises resolve_attr_bridges() and verifies the bridge edge connects the GN
Store Named Attribute writer to the shader Attribute reader via cook-then-read.
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))

from synthgen.scenegraph.backend_bpy import LiveGraph
from synthgen.scenegraph import traverse

print("=" * 60)
print("  Tier-2 attr_bridge Validation")
print("=" * 60)

graph = LiveGraph()

print("\n[1] Resolving attribute bridges (cook + join) ...")
graph.resolve_attr_bridges()

bridge_count = sum(len(v) for v in graph._bridge_edges.values())
print(f"    Bridge edges found: {bridge_count}")

if bridge_count == 0:
    print("    ERROR: no bridge edges resolved!")
    sys.exit(1)

print("\n[2] Bridge edge details:")
for src_id, edges in graph._bridge_edges.items():
    for e in edges:
        print(f"    src:  {e.src}")
        print(f"    dst:  {e.dst}")
        print(f"    type: {e.type}  tier: {e.tier}  state_dependent: {e.state_dependent}")
        print(f"    data: {e.data}")
        print()

print("[3] attribute_trace('inst_color') ...")
trace = traverse.attribute_trace(graph, "inst_color")
print(f"    Edges found: {len(trace['edges'])}")
for e in trace["edges"]:
    print(f"    {e.src} -> {e.dst}  attr={e.data.get('attr')}")

print("\n[4] impact_set from writer node ...")
writer_id = "NG:GN_TestTree/NODE:Store Named Attribute"
impacted = traverse.impact_set(graph, writer_id, edge_types={"attr_bridge"})
print(f"    Nodes impacted by changing {writer_id}:")
for nid in sorted(impacted):
    print(f"      {nid}")

print("\n[5] Reachable from reader node (should include writer) ...")
reader_id = "MAT:TestMaterial/NODE:Attribute"
reach = traverse.reachable(graph, reader_id)
print(f"    Reachable from {reader_id}: {len(reach)} nodes")
writer_reachable = writer_id in reach
print(f"    Writer reachable: {writer_reachable}")

report = {
    "bridge_edges": [
        {
            "src": e.src, "dst": e.dst, "type": e.type,
            "tier": e.tier, "state_dependent": e.state_dependent,
            "resolved": e.resolved, "data": e.data,
        }
        for edges in graph._bridge_edges.values()
        for e in edges
    ],
    "attribute_trace_inst_color": {
        "count": len(trace["edges"]),
        "edges": [
            {"src": e.src, "dst": e.dst, "attr": e.data.get("attr")}
            for e in trace["edges"]
        ],
    },
    "impact_set_from_writer": sorted(impacted),
    "writer_reachable_from_reader": writer_reachable,
}

out_dir = os.path.join(PROJECT_DIR, "validation")
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "attr_bridge_report.json")
with open(out_path, "w") as f:
    json.dump(report, f, indent=2)

print(f"\n[6] Report written to {out_path}")

all_ok = (
    bridge_count >= 1
    and len(trace["edges"]) >= 1
    and len(impacted) >= 1
    and writer_reachable
)

if all_ok:
    print("\n  ALL CHECKS PASSED")
else:
    print("\n  SOME CHECKS FAILED")
    sys.exit(1)

print("=" * 60)
