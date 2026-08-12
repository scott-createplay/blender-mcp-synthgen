#!/usr/bin/env python3
"""
Query the extracted node schemas — grounding, not model memory.

The schemas (produced by synthgen.extract.node_schema, run inside Blender) are too big to hold
in context. This is how the agent looks up ground truth for a node before writing bpy code,
instead of guessing socket identifiers.

Usage:
  python -m synthgen.schema.query [--gn|--shader|--compositor] <command> [arg]

Commands:
  find <substring>     nodes whose id/label matches
  show <NodeIdOrLabel> full sockets + settings for one node
  socket <substring>   nodes that have a socket named/id'd like this
  type <SOCKET_TYPE>   nodes with a socket of this type (MATRIX, ROTATION, ...)
  setting <substring>  nodes with an enum setting matching (e.g. "domain")
  stats                counts

Schema resolution: data/schemas/<BLENDER_DIR>/{gn,shader,compositor}.json at the repo root,
or override the directory with $SYNTHGEN_SCHEMA_DIR.
"""

import json
import os
import sys

BLENDER_DIR = "blender-5.2"
_KEY_TO_FILE = {"gn": "gn.json", "shader": "shader.json", "compositor": "compositor.json"}


def _default_schema_dir():
    # src/synthgen/schema/query.py -> repo root is three parents up
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "..", "data", "schemas", BLENDER_DIR))


def load_schema(key="gn"):
    schema_dir = os.environ.get("SYNTHGEN_SCHEMA_DIR") or _default_schema_dir()
    path = os.path.join(schema_dir, _KEY_TO_FILE[key])
    if not os.path.isfile(path):
        sys.exit(f"schema not found: {path}\n"
                 f"Set $SYNTHGEN_SCHEMA_DIR or regenerate with synthgen.extract.node_schema.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f), path


def sig(node):
    ins = ", ".join(s["identifier"] for s in node["inputs"]) or "-"
    outs = ", ".join(s["identifier"] for s in node["outputs"]) or "-"
    return f'{node["label"]!r}  ({ins})  ->  ({outs})'


def resolve(nodes, key):
    if key in nodes:
        return key, nodes[key]
    kl = key.lower()
    exact = [nid for nid, n in nodes.items() if n["label"].lower() == kl]
    if len(exact) == 1:
        return exact[0], nodes[exact[0]]
    partial = [nid for nid, n in nodes.items() if kl in nid.lower() or kl in n["label"].lower()]
    if len(partial) == 1:
        return partial[0], nodes[partial[0]]
    if not partial:
        sys.exit(f"no node matches {key!r}")
    print(f"ambiguous {key!r}, {len(partial)} matches:")
    for nid in sorted(partial):
        print(f"  {nid:45}  {nodes[nid]['label']}")
    sys.exit(1)


def cmd_find(nodes, term):
    t = term.lower()
    hits = {nid: n for nid, n in nodes.items() if t in nid.lower() or t in n["label"].lower()}
    for nid in sorted(hits):
        print(f"{nid:48}  {sig(hits[nid])}")
    print(f"\n{len(hits)} match(es).")


def cmd_show(nodes, key):
    nid, n = resolve(nodes, key)
    print(f"{n['label']}   [{nid}]")
    print("  inputs:")
    for s in n["inputs"]:
        tag = "" if s["name"] == s["identifier"] else f'   (label: {s["name"]!r})'
        print(f'    {s["identifier"]:24} {s["type"]:10}{tag}')
    print("  outputs:")
    for s in n["outputs"]:
        tag = "" if s["name"] == s["identifier"] else f'   (label: {s["name"]!r})'
        print(f'    {s["identifier"]:24} {s["type"]:10}{tag}')
    if n["settings"]:
        print("  settings (enum):")
        for st in n["settings"]:
            print(f'    {st["name"]:20} = {st["default"]!r}   one of: {st["values"]}')


def cmd_socket(nodes, term):
    t = term.lower()
    for nid in sorted(nodes):
        for io in ("inputs", "outputs"):
            for s in nodes[nid][io]:
                if t in s["name"].lower() or t in s["identifier"].lower():
                    print(f'{nid:46} {io[:-1]:6} {s["identifier"]:22} {s["type"]}')


def cmd_type(nodes, term):
    t = term.upper()
    for nid in sorted(nodes):
        for io in ("inputs", "outputs"):
            for s in nodes[nid][io]:
                if s["type"] == t:
                    print(f'{nid:46} {io[:-1]:6} {s["identifier"]}')


def cmd_setting(nodes, term):
    t = term.lower()
    for nid in sorted(nodes):
        for st in nodes[nid]["settings"]:
            if t in st["name"].lower():
                print(f'{nid:46} {st["name"]:16} {st["values"]}')


def cmd_stats(schema):
    nodes = schema["nodes"]
    geo = sum(1 for k in nodes if k.startswith("GeometryNode"))
    fn = sum(1 for k in nodes if k.startswith("FunctionNode"))
    sh = sum(1 for k in nodes if k.startswith("ShaderNode"))
    co = sum(1 for k in nodes if k.startswith("CompositorNode"))
    print(f'{schema.get("tree_type", "?")}  |  Blender {schema.get("blender_version")}')
    print(f'{len(nodes)} nodes  (Geometry {geo}, Function {fn}, Shader {sh}, Compositor {co}, '
          f'other {len(nodes) - geo - fn - sh - co})')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    key = "gn"
    for flag, k in (("--shader", "shader"), ("--compositor", "compositor"), ("--gn", "gn")):
        if flag in argv:
            key = k
            argv.remove(flag)
    if not argv:
        print(__doc__)
        return
    schema, _ = load_schema(key)
    nodes = schema["nodes"]
    cmd, arg = argv[0], (argv[1] if len(argv) > 1 else "")
    dispatch = {
        "find": lambda: cmd_find(nodes, arg),
        "show": lambda: cmd_show(nodes, arg),
        "socket": lambda: cmd_socket(nodes, arg),
        "type": lambda: cmd_type(nodes, arg),
        "setting": lambda: cmd_setting(nodes, arg),
        "stats": lambda: cmd_stats(schema),
    }
    if cmd not in dispatch:
        sys.exit(f"unknown command {cmd!r}. See --help.\n{__doc__}")
    dispatch[cmd]()


if __name__ == "__main__":
    main()
