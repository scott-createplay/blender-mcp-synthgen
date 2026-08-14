"""MCP tools for synthetic data pipeline — parameter control, rendering, and sweeping.

Layer 4 (orchestration) tools drive the render/sweep loop:
set parameters, render, sweep parameter combinations, export labels.
"""

from __future__ import annotations

import json
import os
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _src_path() -> str:
    """Path to the src/ directory — same-machine assumption (see graph.py)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", ".."))


def register(mcp: FastMCP, get_transport, get_blender_dir=None) -> None:
    # Internal helpers (same pattern as blender.py)
    def _run(code: str, mutates: bool = False) -> str:
        transport = get_transport()
        if mutates:
            transport.mark_dirty()
        result = transport.execute_python(code)
        if isinstance(result, dict):
            return result.get("output", json.dumps(result))
        return str(result)

    def _resolve_dirty_code() -> str:
        """Build a snippet that resolves attribute bridges if the scene is dirty.

        Mirrors the pattern in graph.py's _graph_preamble, but is applied
        manually here since render/sweep aren't graph-introspection tools —
        they still need to cook the depsgraph before writing pixels.
        """
        transport = get_transport()
        if not transport.dirty:
            return ""
        transport.clear_dirty()
        return textwrap.dedent(f"""\
            sys.path.insert(0, r'{_src_path()}')
            from synthgen.scenegraph.backend_bpy import LiveGraph
            g = LiveGraph()
            g.resolve_attr_bridges()
        """)

    # --- Layer 4: Orchestration ---------------------------------------------

    @mcp.tool()
    def set_parameter(
        object_name: str,
        modifier_name: str,
        socket_identifier: str,
        value: str | float | int | list | bool,
    ) -> str:
        """Set a Geometry Nodes modifier input value. Use after expose_parameter
        to control procedural parameters externally. This is the entry point for
        sweep — vary these values to generate dataset diversity.

        Args:
            object_name: Name of the object with the GN modifier.
            modifier_name: Name of the Geometry Nodes modifier.
            socket_identifier: Socket identifier from expose_parameter output
                              (e.g. "Socket_2", not the display name).
            value: Value to set — float, int, bool, or list for vectors.
        """
        code = textwrap.dedent(f"""\
            import bpy, json
            obj = bpy.data.objects.get({object_name!r})
            if not obj:
                print(f"ERROR: object {object_name!r} not found")
            else:
                mod = obj.modifiers.get({modifier_name!r})
                if not mod:
                    print(f"ERROR: modifier {modifier_name!r} not found on {{obj.name}}")
                else:
                    ver = bpy.app.version
                    ok = False
                    if ver >= (5, 0, 0):
                        # Blender 5.x: GN modifier inputs live under mod.properties.inputs
                        inp = getattr(mod.properties.inputs, {socket_identifier!r}, None)
                        if inp is not None:
                            inp.default_value = {value!r}
                            ok = True
                        else:
                            print(f"ERROR: socket {socket_identifier!r} not found on mod.properties.inputs (Blender {{ver[0]}}.{{ver[1]}}, tried 5.x API)")
                    else:
                        # Blender 4.x: id-property API
                        try:
                            mod[{socket_identifier!r}] = {value!r}
                            ok = True
                        except Exception as _e:
                            print(f"ERROR: failed to set socket {socket_identifier!r} via mod[...] (Blender {{ver[0]}}.{{ver[1]}}, tried 4.x API): {{_e}}")
                    if ok:
                        print(json.dumps({{
                            "object": obj.name,
                            "modifier": mod.name,
                            "socket": {socket_identifier!r},
                            "value": {value!r},
                        }}))
        """)
        return _run(code, mutates=True)

    @mcp.tool()
    def render(
        output_path: str | None = None,
        save_provenance: bool = True,
    ) -> str:
        """Render the current scene to a file. Resolves any pending attribute
        bridges before rendering. Optionally saves a provenance snapshot
        alongside the output for reproducibility.

        Args:
            output_path: Output file path. If omitted, uses scene.render.filepath.
            save_provenance: Save graph provenance JSON alongside output (default True).
        """
        resolve_code = _resolve_dirty_code()

        filepath_line = f"scene.render.filepath = {output_path!r}" if output_path else ""

        provenance_code = ""
        if save_provenance:
            provenance_code = textwrap.dedent("""\
                from synthgen.scenegraph.backend_bpy import LiveGraph
                g2 = LiveGraph()
                nodes = sorted(g2.nodes())
                edges = []
                for nid in nodes:
                    for e in g2.neighbors(nid):
                        edges.append({"src": e.src, "dst": e.dst, "type": e.type,
                                       "tier": e.tier, "data": e.data})
                prov_path = scene.render.filepath + ".provenance.json"
                import json as _json
                with open(prov_path, "w") as f:
                    _json.dump({"nodes": nodes, "edges": edges,
                                "output": scene.render.filepath}, f, indent=2)
                result["provenance_path"] = prov_path
            """)

        code = "import sys, bpy, json\n"
        code += resolve_code
        code += textwrap.dedent(f"""\
            scene = bpy.context.scene
            {filepath_line}
            result = {{"output_path": scene.render.filepath}}
            bpy.ops.render.render(write_still=True)
        """)
        code += provenance_code
        code += "print(json.dumps(result))\n"

        return _run(code, mutates=False)

    @mcp.tool()
    def sweep(
        object_name: str,
        modifier_name: str,
        parameters: list[dict],
        output_dir: str,
        seeds: list[int] | None = None,
        file_format: str = "PNG",
        save_provenance: bool = True,
    ) -> str:
        """Sweep parameter combinations and render each — the core synthetic data
        generation loop. Generates one image per parameter combo x seed.

        Each parameter dict specifies a socket and its values to iterate.
        All parameters are crossed (cartesian product).

        Args:
            object_name: Object with the GN modifier.
            modifier_name: Name of the GN modifier.
            parameters: List of parameter specs, each:
                       {"socket": "Socket_2", "values": [0.1, 0.5, 1.0]}
            output_dir: Directory for rendered outputs.
            seeds: Optional list of random seeds to iterate. If provided, sets
                  scene.render.seed (Cycles) for each value.
            file_format: Output format — "PNG", "OPEN_EXR", "JPEG".
            save_provenance: Save provenance JSON per sample (default True).
        """
        resolve_code = _resolve_dirty_code()

        ext_map = {"PNG": "png", "OPEN_EXR": "exr", "JPEG": "jpg"}
        ext = ext_map.get(file_format, file_format.lower())

        sockets = [p["socket"] for p in parameters]
        value_lists = [p["values"] for p in parameters]
        seed_list = seeds if seeds is not None else [None]

        # Build the innermost loop body (per-sample render + provenance) at its
        # own 0-base indentation, then shift the whole thing into place with
        # textwrap.indent — avoids stacking independently-dedented fragments
        # with mismatched margins (which silently produces wrong nesting).
        sample_body = textwrap.dedent("""\
            sample = {
                "output_path": filepath,
                "parameters": dict(zip(sockets, combo)),
                "seed": seed,
            }
        """)
        if save_provenance:
            sample_body += textwrap.dedent("""\
                from synthgen.scenegraph.backend_bpy import LiveGraph
                g2 = LiveGraph()
                pnodes = sorted(g2.nodes())
                pedges = []
                for nid in pnodes:
                    for e in g2.neighbors(nid):
                        pedges.append({"src": e.src, "dst": e.dst, "type": e.type,
                                        "tier": e.tier, "data": e.data})
                prov_path = filepath + ".provenance.json"
                with open(prov_path, "w") as f:
                    json.dump({"nodes": pnodes, "edges": pedges,
                               "output": filepath}, f, indent=2)
                sample["provenance_path"] = prov_path
            """)
        sample_body += "manifest.append(sample)\n"

        loop_body = textwrap.dedent(f"""\
            parts = [f"{{s}}-{{v}}" for s, v in zip(sockets, combo)]
            if seed is not None:
                scene.cycles.seed = seed
                parts.append(f"seed-{{seed}}")
            name = "_".join(parts).replace(" ", "")
            filepath = os.path.join(output_dir, f"{{name}}.{ext}")
            scene.render.filepath = filepath
            bpy.ops.render.render(write_still=True)
        """) + sample_body

        for_seed_block = textwrap.dedent("""\
            for socket, value in zip(sockets, combo):
                if bpy.app.version >= (5, 0, 0):
                    inp = getattr(mod.properties.inputs, socket, None)
                    if inp is not None:
                        inp.default_value = value
                    else:
                        print(f"WARNING: socket {socket} not found on mod.properties.inputs")
                else:
                    mod[socket] = value
            for seed in seed_list:
        """) + textwrap.indent(loop_body, "    ")

        for_combo_block = "for combo in itertools.product(*value_lists):\n" + textwrap.indent(for_seed_block, "    ")

        success_block = textwrap.dedent(f"""\
            scene.render.image_settings.file_format = {file_format!r}
            sockets = {sockets!r}
            value_lists = {value_lists!r}
            seed_list = {seed_list!r}
            output_dir = {output_dir!r}
            os.makedirs(output_dir, exist_ok=True)
        """) + for_combo_block + 'print(json.dumps({"count": len(manifest), "samples": manifest}, indent=2))\n'

        mod_block = textwrap.dedent(f"""\
            mod = obj.modifiers.get({modifier_name!r})
            if not mod:
                print(json.dumps({{"error": f"modifier {modifier_name!r} not found on {{obj.name}}"}}))
            else:
        """) + textwrap.indent(success_block, "    ")

        main_block = textwrap.dedent(f"""\
            scene = bpy.context.scene
            obj = bpy.data.objects.get({object_name!r})
            manifest = []
            if not obj:
                print(json.dumps({{"error": f"object {object_name!r} not found"}}))
            else:
        """) + textwrap.indent(mod_block, "    ")

        code = "import sys, os, itertools, bpy, json\n"
        code += resolve_code
        code += main_block

        return _run(code, mutates=False)

    @mcp.tool()
    def export_labels(
        output_dir: str | None = None,
    ) -> str:
        """Export ground-truth label metadata from the current scene setup.

        Inspects compositor File Output nodes to identify which render passes
        are configured and where they write. Returns a manifest mapping each
        output channel to its semantic role.

        Use after wire_compositor_pass to verify the label pipeline is wired.

        Args:
            output_dir: Optional directory to scan for existing outputs. If omitted,
                       reads paths from compositor File Output nodes.
        """
        code = textwrap.dedent(f"""\
            import bpy, json
            scene = bpy.context.scene
            tree = scene.compositing_node_group
            manifest = {{"file_outputs": [], "render_layers": []}}
            if tree is None:
                print(json.dumps(manifest))
            else:
                for n in tree.nodes:
                    if n.bl_idname == 'CompositorNodeOutputFile':
                        inputs = []
                        for s in n.inputs:
                            linked = s.is_linked
                            from_node = None
                            from_socket = None
                            if linked:
                                link = s.links[0]
                                from_node = link.from_node.name
                                from_socket = link.from_socket.identifier
                            inputs.append({{
                                "name": s.name,
                                "linked": linked,
                                "from_node": from_node,
                                "from_socket": from_socket,
                            }})
                        manifest["file_outputs"].append({{
                            "node": n.name,
                            "base_path": n.base_path,
                            "format": n.format.file_format,
                            "inputs": inputs,
                        }})
                    elif n.bl_idname == 'CompositorNodeRLayers':
                        enabled_passes = [s.name for s in n.outputs if s.enabled]
                        manifest["render_layers"].append({{
                            "node": n.name,
                            "layer": n.layer,
                            "enabled_passes": enabled_passes,
                        }})
                print(json.dumps(manifest, indent=2))
        """)
        return _run(code, mutates=False)
