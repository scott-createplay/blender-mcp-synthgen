"""Validate LiveGraph walker against a pre-built Blender scene.

Run inside Blender headless:
    blender -b scenes/test_scene.blend -P scripts/validate_livegraph.py

Enumerates all nodes, collects all edges, runs reachable() from every
top-level collection and object node, and writes a structured JSON report
to validation/walker_report.json.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from dataclasses import asdict

# ---------------------------------------------------------------------------
# 1. Ensure synthgen is importable (src/ layout relative to project root)
# ---------------------------------------------------------------------------
_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
_src_dir = os.path.join(_project_root, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# ---------------------------------------------------------------------------
# 2. Imports
# ---------------------------------------------------------------------------
from synthgen.scenegraph.backend_bpy import LiveGraph   # noqa: E402
from synthgen.scenegraph.traverse import reachable      # noqa: E402

# ---------------------------------------------------------------------------
# 3. Instantiate the graph
# ---------------------------------------------------------------------------
graph = LiveGraph()

# ---------------------------------------------------------------------------
# Collection structures for the report
# ---------------------------------------------------------------------------
all_nodes: list[dict] = []
all_edges: list[dict] = []
reachable_from: dict[str, list[str]] = {}
errors: list[dict] = []

# ---------------------------------------------------------------------------
# 4. Enumerate ALL nodes
# ---------------------------------------------------------------------------
node_ids: list[str] = []
try:
    node_ids = list(graph.nodes())
except Exception as exc:
    errors.append({"node_id": "__nodes__", "error": f"nodes() raised: {exc}"})

for nid in node_ids:
    try:
        info = graph.resolve(nid)
        kind = info.get("kind") if info else None
    except Exception as exc:
        kind = None
        errors.append({"node_id": nid, "error": f"resolve() raised: {exc}"})
    all_nodes.append({"id": nid, "kind": kind})

# ---------------------------------------------------------------------------
# 5. For EVERY node, collect outgoing edges via neighbors()
# ---------------------------------------------------------------------------
for nid in node_ids:
    try:
        for edge in graph.neighbors(nid):
            all_edges.append(asdict(edge))
    except Exception as exc:
        errors.append({"node_id": nid, "error": f"neighbors() raised: {exc}"})

# ---------------------------------------------------------------------------
# 6. Run reachable() from every COL: and OBJ: top-level node
# ---------------------------------------------------------------------------
top_level_ids = [
    nid for nid in node_ids
    if (nid.startswith("COL:") or nid.startswith("OBJ:")) and "/MOD:" not in nid
]
for nid in top_level_ids:
    try:
        r = reachable(graph, nid)
        reachable_from[nid] = sorted(r)
    except Exception as exc:
        errors.append({"node_id": nid, "error": f"reachable() raised: {exc}"})

# ---------------------------------------------------------------------------
# 7. Build summary
# ---------------------------------------------------------------------------
prefix_counter: Counter = Counter()
for n in all_nodes:
    prefix = n["id"].split(":")[0]
    # For nested ids like OBJ:X/MOD:Y, the prefix is OBJ but the tail prefix
    # is MOD. Use the tail segment's prefix for granularity.
    tail = n["id"].rsplit("/", 1)[-1]
    tail_prefix = tail.split(":")[0]
    prefix_counter[tail_prefix] += 1

edge_type_counter: Counter = Counter()
for e in all_edges:
    edge_type_counter[e["type"]] += 1

summary = {
    "total_nodes": len(all_nodes),
    "nodes_by_prefix": dict(prefix_counter),
    "total_edges": len(all_edges),
    "edges_by_type": dict(edge_type_counter),
}

# ---------------------------------------------------------------------------
# 8. Write report JSON
# ---------------------------------------------------------------------------
report = {
    "nodes": all_nodes,
    "edges": all_edges,
    "reachable_from": reachable_from,
    "errors": errors,
    "summary": summary,
}

output_dir = os.path.join(_project_root, "validation")
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, "walker_report.json")

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# 9. Print human-readable summary to stdout
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("  LiveGraph Walker Validation Report")
print("=" * 60)
print()
print(f"Total nodes discovered: {summary['total_nodes']}")
print("  Nodes by kind prefix:")
for prefix, count in sorted(prefix_counter.items()):
    print(f"    {prefix}: {count}")
print()
print(f"Total edges discovered: {summary['total_edges']}")
print("  Edges by type:")
for etype, count in sorted(edge_type_counter.items()):
    print(f"    {etype}: {count}")
print()
print(f"Reachable sets computed: {len(reachable_from)}")
for nid, r_set in sorted(reachable_from.items()):
    print(f"  {nid} -> {len(r_set)} reachable nodes")
print()
if errors:
    print(f"ERRORS encountered: {len(errors)}")
    for err in errors:
        print(f"  [{err['node_id']}] {err['error']}")
else:
    print("No errors encountered.")
print()
print(f"Report written to: {output_path}")
print("=" * 60)
