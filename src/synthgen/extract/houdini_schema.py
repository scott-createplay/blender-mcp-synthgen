"""
dump_houdini_schema.py — Houdini node-schema extractor.  (h-v1)

Run inside Houdini: Windows ▸ Python Shell  (or:  hython dump_houdini_schema.py).
Enumerates Houdini's own node-type categories and dumps, for the relevant contexts,
each node type's internal name, label (description), and parameter names — so the
Houdini↔Blender crosswalks become VERIFIED, not from-memory. Critically, it prints
EVERY category name it finds, so we learn what the Copernicus COP context is actually
called in THIS build (H20.5/H21/H22 differ) rather than guessing.

Output: <home>/houdini_schema.json   (path printed at the end).

Why these contexts:
  Sop  — geometry            -> Blender Geometry Nodes
  Vop  — VEX node graphs     -> Blender field graphs / shader nodes
  Cop  — Copernicus (new)    -> Blender Compositor
  Cop2 — classic COP2 (old)  -> Blender Compositor
"""

import hou
import json
import os


# Capture full type+param detail only for these (keeps the file bounded); every
# other category is still listed by name + count so nothing is hidden.
DETAIL_CATEGORIES = {"Sop", "Vop", "Cop", "Cop2", "CopNet", "Copernicus"}


def flatten_parms(ptg):
    """Top-level + folder-nested parm (name, label, type) triples, best-effort."""
    out = []

    def walk(templates):
        for pt in templates:
            try:
                out.append({
                    "name": pt.name(),
                    "label": pt.label(),
                    "type": type(pt).__name__.replace("ParmTemplate", ""),
                })
            except Exception:
                pass
            # recurse into folders
            try:
                sub = pt.parmTemplates()
            except Exception:
                sub = None
            if sub:
                walk(sub)

    try:
        walk(ptg.parmTemplates())
    except Exception:
        pass
    return out


def dump_category(cat, detailed):
    types = {}
    try:
        node_types = cat.nodeTypes()
    except Exception:
        return types
    for tname, ntype in node_types.items():
        entry = {"label": ""}
        try:
            entry["label"] = ntype.description()
        except Exception:
            pass
        if detailed:
            try:
                entry["parms"] = flatten_parms(ntype.parmTemplateGroup())
            except Exception:
                entry["parms"] = []
        types[tname] = entry
    return types


def main():
    schema = {
        "extractor_version": "h-v1",
        "houdini_version": hou.applicationVersionString(),
        "all_categories": {},   # name -> node-type count (so we SEE what exists)
        "categories": {},       # detailed dumps for DETAIL_CATEGORIES that exist
    }

    cats = hou.nodeTypeCategories()
    for name, cat in cats.items():
        try:
            count = len(cat.nodeTypes())
        except Exception:
            count = -1
        schema["all_categories"][name] = count

    for name, cat in cats.items():
        detailed = name in DETAIL_CATEGORIES
        if detailed:
            schema["categories"][name] = dump_category(cat, detailed=True)

    out_path = os.path.join(os.path.expanduser("~"), "houdini_schema.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    print("=" * 64)
    print(f"[h-v1] Houdini {schema['houdini_version']}")
    print("all categories found (name: type_count):")
    for n in sorted(schema["all_categories"]):
        star = "  <-- detailed" if n in schema["categories"] else ""
        print(f"   {n:16} {schema['all_categories'][n]:5}{star}")
    print(f"Wrote: {out_path}")
    print("=" * 64)


main()
