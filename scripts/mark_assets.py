"""
mark_assets.py -- Register SynthGen node groups as Blender assets.

Run headless (from the project root):
    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" -b -P scripts/mark_assets.py

Produces:
    assets/blender_assets.cats.txt  -- catalog hierarchy (idempotent write)
    assets/scatter.blend            -- node groups renamed + asset-marked with metadata

Self-verifying: runs a verification pass after marking and reports results.
"""

import bpy
import os
import sys

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR = os.path.join(PROJECT_DIR, "assets")
CATALOG_PATH = os.path.join(ASSETS_DIR, "blender_assets.cats.txt")

print(f"[mark] Project root : {PROJECT_DIR}")
print(f"[mark] Assets dir   : {ASSETS_DIR}")

# ---------------------------------------------------------------------------
# Catalog UUIDs (stable, generated once)
# ---------------------------------------------------------------------------
CATALOG_ROOT_UUID = "e18a1b41-afdb-4720-9301-068347e18f12"
CATALOG_DIST_UUID = "21442b1d-30de-4288-a6f7-52d3d19b71a6"
CATALOG_INST_UUID = "106165cc-64d3-4148-8901-c3de44bab598"

# ---------------------------------------------------------------------------
# Asset definitions
# ---------------------------------------------------------------------------
ASSET_DEFINITIONS = [
    {
        "old_name": "Scatter on Surface",
        "new_name": "SynthGen.Scatter on Surface",
        "description": (
            "Distributes points across a mesh surface with per-element"
            " density control, exact count mode, and well-known attribute"
            " output."
        ),
        "author": "SynthGen",
        "catalog_id": CATALOG_DIST_UUID,
        "tags": ["scatter", "distribution", "points", "density"],
    },
    {
        "old_name": "Instance on Points",
        "new_name": "SynthGen.Instance on Points",
        "description": (
            "Places instances from a collection onto input points, reading"
            " transform attributes from the geometry."
        ),
        "author": "SynthGen",
        "catalog_id": CATALOG_INST_UUID,
        "tags": ["instance", "instancing", "points", "collection"],
    },
]

SKIP_GROUPS = {"SynthGen"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _check(label, condition, detail=""):
    status = "OK" if condition else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return condition


def write_catalog():
    """Write the catalog hierarchy file. Idempotent -- overwrites if exists."""
    content = (
        "VERSION 1\n"
        "\n"
        f"{CATALOG_ROOT_UUID}:SynthGen:SynthGen\n"
        f"{CATALOG_DIST_UUID}:SynthGen/Distribution:SynthGen-Distribution\n"
        f"{CATALOG_INST_UUID}:SynthGen/Instancing:SynthGen-Instancing\n"
    )
    with open(CATALOG_PATH, "w", newline="\n") as f:
        f.write(content)
    print(f"[mark] Catalog written: {CATALOG_PATH}")


def rename_node_group(ng, new_name):
    """Rename a node group with collision safety. Idempotent."""
    if ng.name == new_name:
        print(f"[mark]   Already named: {new_name!r}")
        return
    existing = bpy.data.node_groups.get(new_name)
    if existing is not None and existing != ng:
        print(f"[mark]   Removing stale duplicate: {new_name!r}")
        bpy.data.node_groups.remove(existing)
    old = ng.name
    ng.name = new_name
    if ng.name != new_name:
        print(f"[mark]   ERROR: rename produced {ng.name!r} instead of {new_name!r}")
        sys.exit(1)
    print(f"[mark]   Renamed: {old!r} -> {ng.name!r}")


def mark_asset(ng, defn):
    """Mark a node group as an asset with full metadata. Idempotent."""
    ng.asset_mark()
    ad = ng.asset_data
    ad.description = defn["description"]
    ad.author = defn["author"]
    ad.catalog_id = defn["catalog_id"]

    while len(ad.tags) > 0:
        ad.tags.remove(ad.tags[0])
    for tag in defn["tags"]:
        ad.tags.new(tag)

    print(f"[mark]   Marked as asset: {ng.name!r}")
    print(f"[mark]     catalog_id: {ad.catalog_id}")
    print(f"[mark]     tags: {[t.name for t in ad.tags]}")


def process_blend(filepath):
    """Open a .blend file, rename + mark matching node groups, save."""
    print(f"\n[mark] Processing: {filepath}")
    bpy.ops.wm.open_mainfile(filepath=filepath)

    for defn in ASSET_DEFINITIONS:
        ng = (bpy.data.node_groups.get(defn["old_name"])
              or bpy.data.node_groups.get(defn["new_name"]))
        if ng is None:
            print(f"[mark]   SKIP: {defn['old_name']!r} not found in this file")
            continue
        rename_node_group(ng, defn["new_name"])
        mark_asset(ng, defn)

    for skip_name in SKIP_GROUPS:
        skip_ng = bpy.data.node_groups.get(skip_name)
        if skip_ng and skip_ng.asset_data:
            print(f"[mark]   WARNING: {skip_name!r} is asset-marked but shouldn't be")

    bpy.ops.wm.save_as_mainfile(filepath=filepath)
    print(f"[mark] Saved: {filepath}")


def verify(filepath):
    """Reopen the saved .blend and verify asset marks survived."""
    print(f"\n[verify] Reopening: {filepath}")
    bpy.ops.wm.open_mainfile(filepath=filepath)

    all_ok = True
    for defn in ASSET_DEFINITIONS:
        ng = bpy.data.node_groups.get(defn["new_name"])
        if not _check(f"{defn['new_name']!r} exists", ng is not None):
            all_ok = False
            continue

        if not _check(f"{ng.name} is asset-marked", ng.asset_data is not None):
            all_ok = False
            continue

        ad = ng.asset_data
        all_ok &= _check(
            f"{ng.name} catalog_id",
            ad.catalog_id == defn["catalog_id"],
            f"expected {defn['catalog_id']}, got {ad.catalog_id}",
        )
        all_ok &= _check(
            f"{ng.name} description",
            ad.description == defn["description"],
            f"len={len(ad.description)}",
        )
        all_ok &= _check(f"{ng.name} author", ad.author == defn["author"])

        actual_tags = sorted(t.name for t in ad.tags)
        expected_tags = sorted(defn["tags"])
        all_ok &= _check(
            f"{ng.name} tags",
            actual_tags == expected_tags,
            f"expected {expected_tags}, got {actual_tags}",
        )

    for skip_name in SKIP_GROUPS:
        skip_ng = bpy.data.node_groups.get(skip_name)
        if skip_ng:
            all_ok &= _check(
                f"{skip_name!r} NOT asset-marked",
                skip_ng.asset_data is None,
            )

    container = bpy.data.node_groups.get("SynthGen")
    if container:
        for node in container.nodes:
            if node.type == "GROUP" and node.node_tree:
                all_ok &= _check(
                    f"Container node {node.name!r} references renamed tree",
                    node.node_tree.name.startswith("SynthGen."),
                    f"tree={node.node_tree.name!r}",
                )

    return all_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("  SynthGen Asset Registration")
    print("=" * 60)

    write_catalog()

    blend_files = sorted(
        os.path.join(ASSETS_DIR, f)
        for f in os.listdir(ASSETS_DIR)
        if f.endswith(".blend") and not f.endswith(".autosave.blend")
    )
    print(f"[mark] Found {len(blend_files)} .blend file(s)")

    for bf in blend_files:
        process_blend(bf)

    all_ok = True
    for bf in blend_files:
        all_ok &= verify(bf)

    print("\n" + "=" * 60)
    if all_ok:
        print("  ALL VERIFICATIONS PASSED")
    else:
        print("  SOME VERIFICATIONS FAILED")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
