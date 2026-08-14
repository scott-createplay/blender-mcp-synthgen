#!/usr/bin/env python3
"""Build the synthgen_mcp addon zip for Blender installation.

Creates synthgen_mcp.zip containing:
  synthgen_mcp/
    __init__.py, executor.py, server.py, ui.py, deps.py
    synthgen/          (bundled from src/synthgen/)
    data/schemas/      (bundled from data/schemas/)

Usage:
  python scripts/build_addon.py [--output path/to/output.zip]
"""

import argparse
import os
import shutil
import sys
import tempfile
import zipfile

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

ADDON_FILES = [
    "__init__.py",
    "executor.py",
    "server.py",
    "ui.py",
    "deps.py",
]

SKIP_PATTERNS = {
    "__pycache__",
    ".pyc",
    ".pyo",
    ".egg-info",
    ".pytest_cache",
    "vendor",
}


def should_skip(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(skip in part for part in parts for skip in SKIP_PATTERNS)


def build(output_path: str) -> str:
    addon_src = os.path.join(REPO_ROOT, "addon", "synthgen_mcp")
    synthgen_src = os.path.join(REPO_ROOT, "src", "synthgen")
    schemas_src = os.path.join(REPO_ROOT, "data", "schemas")

    for d in [addon_src, synthgen_src, schemas_src]:
        if not os.path.isdir(d):
            sys.exit(f"Required directory not found: {d}")

    with tempfile.TemporaryDirectory() as tmpdir:
        pkg = os.path.join(tmpdir, "synthgen_mcp")
        os.makedirs(pkg)

        for fname in ADDON_FILES:
            src = os.path.join(addon_src, fname)
            if not os.path.isfile(src):
                sys.exit(f"Addon file not found: {src}")
            shutil.copy2(src, os.path.join(pkg, fname))

        dst_synthgen = os.path.join(pkg, "synthgen")
        shutil.copytree(
            synthgen_src,
            dst_synthgen,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )

        dst_schemas = os.path.join(pkg, "data", "schemas")
        shutil.copytree(schemas_src, dst_schemas)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(pkg):
                dirs[:] = [d for d in dirs if d not in SKIP_PATTERNS]
                for f in files:
                    full = os.path.join(root, f)
                    arcname = os.path.relpath(full, tmpdir)
                    if not should_skip(arcname):
                        zf.write(full, arcname)

    size_kb = os.path.getsize(output_path) / 1024
    print(f"Built {output_path} ({size_kb:.0f} KB)")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Build synthgen_mcp addon zip")
    parser.add_argument(
        "--output", "-o",
        default=os.path.join(REPO_ROOT, "dist", "synthgen_mcp.zip"),
        help="Output zip path (default: dist/synthgen_mcp.zip)",
    )
    args = parser.parse_args()
    build(args.output)


if __name__ == "__main__":
    main()
