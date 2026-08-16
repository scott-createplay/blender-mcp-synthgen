"""Deploy the Synthgen MCP addon to Blender's installed addons directory.

Usage:  python tools/deploy_addon.py
        python tools/deploy_addon.py --blender-version 5.2

Builds a self-contained addon by copying:
  1. addon/synthgen_mcp/    → addon source (server, UI, executor, deps)
  2. src/synthgen/          → bundled as synthgen_mcp/synthgen/
  3. data/schemas/          → bundled as synthgen_mcp/data/schemas/

After deploying, open Blender — the addon auto-starts.
Then run:  python tools/validate_addon.py
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")

_BLENDER_EXE_CANDIDATES = [
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "blender",
]


def _find_blender_addons_dir(version: str | None = None) -> str | None:
    """Locate Blender's user scripts/addons directory."""
    if platform.system() == "Windows":
        base = os.path.join(
            os.environ.get("APPDATA", ""), "Blender Foundation", "Blender"
        )
    elif platform.system() == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/Blender")
    else:
        base = os.path.expanduser("~/.config/blender")

    if not os.path.isdir(base):
        return None

    if version:
        candidate = os.path.join(base, version, "scripts", "addons")
        return candidate if os.path.isdir(os.path.dirname(candidate)) else None

    versions = sorted(
        [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))],
        reverse=True,
    )
    return os.path.join(base, versions[0], "scripts", "addons") if versions else None


def _kill_blender() -> bool:
    """Kill all running Blender processes. Returns True if any were killed."""
    killed = False
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq blender.exe", "/NH"],
                text=True, stderr=subprocess.DEVNULL,
            )
            if "blender.exe" in out.lower():
                subprocess.run(
                    ["taskkill", "/F", "/IM", "blender.exe"],
                    capture_output=True, timeout=10,
                )
                killed = True
        else:
            result = subprocess.run(["pgrep", "-x", "blender"], capture_output=True, text=True)
            if result.returncode == 0:
                subprocess.run(["pkill", "-9", "-x", "blender"], capture_output=True, timeout=10)
                killed = True
    except Exception:
        pass
    if killed:
        time.sleep(1)
    return killed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--blender-version",
        help="Target a specific Blender version (e.g. 5.2). Default: highest installed.",
    )
    args = parser.parse_args()

    if _kill_blender():
        print("  Killed running Blender process(es)\n")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    addon_src = os.path.join(repo_root, "addon", "synthgen_mcp")
    synthgen_src = os.path.join(repo_root, "src", "synthgen")
    schemas_src = os.path.join(repo_root, "data", "schemas")
    knowledge_src = os.path.join(repo_root, "knowledge")

    for label, path in [("addon", addon_src), ("synthgen", synthgen_src), ("schemas", schemas_src)]:
        if not os.path.isdir(path):
            print(f"FAIL  {label} source not found: {path}")
            sys.exit(1)

    addons_dir = _find_blender_addons_dir(args.blender_version)
    if addons_dir is None:
        print("FAIL  Could not find Blender user addons directory")
        sys.exit(1)

    dest = os.path.join(addons_dir, "synthgen_mcp")

    print(f"  addon source:    {addon_src}")
    print(f"  synthgen source: {synthgen_src}")
    print(f"  schemas source:  {schemas_src}")
    print(f"  knowledge source:{' ' if knowledge_src else ''}{knowledge_src}")
    print(f"  target:          {dest}")
    print()

    # Preserve vendor/ if it exists (pip-installed deps, slow to reinstall)
    vendor_backup = None
    vendor_dest = os.path.join(dest, "vendor")
    if os.path.isdir(vendor_dest):
        vendor_backup = dest + "_vendor_backup"
        shutil.move(vendor_dest, vendor_backup)

    if os.path.exists(dest):
        shutil.rmtree(dest)

    # 1. Copy addon source
    shutil.copytree(addon_src, dest, ignore=_IGNORE)
    print("  [1/4] Copied addon source")

    # 2. Bundle synthgen package
    shutil.copytree(synthgen_src, os.path.join(dest, "synthgen"), ignore=_IGNORE)
    print("  [2/4] Bundled synthgen package")

    # 3. Bundle schemas
    shutil.copytree(schemas_src, os.path.join(dest, "data", "schemas"), ignore=_IGNORE)
    print("  [3/4] Bundled schema data")

    # 4. Bundle knowledge files (user-customizable MCP resources)
    if os.path.isdir(knowledge_src):
        shutil.copytree(knowledge_src, os.path.join(dest, "knowledge"), ignore=_IGNORE)
        md_count = len([f for f in os.listdir(knowledge_src) if f.endswith(".md")])
        print(f"  [4/4] Bundled knowledge files ({md_count} .md files)")
    else:
        print("  [4/4] No knowledge/ directory found — skipped")

    # 4. Restore or install vendor/ (pip deps: mcp SDK, starlette, uvicorn, etc.)
    if vendor_backup and os.path.isdir(vendor_backup):
        shutil.move(vendor_backup, vendor_dest)
        print("  [5/5] Restored vendor/ (pip deps preserved)")
    else:
        print("  [5/5] Installing pip deps into vendor/ ...")
        os.makedirs(vendor_dest, exist_ok=True)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install",
                 "--target", vendor_dest, "--upgrade", "--no-user",
                 "mcp[cli]>=1.3.0,<2"],
                timeout=120,
            )
            print("        pip install complete")
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"  WARN  pip install failed: {exc}")
            print("        The addon will try to install deps on first Blender startup.")

    count = sum(len(files) for _, _, files in os.walk(dest))
    print(f"\n  {count} files deployed")

    # 5. Enable addon in Blender user preferences (persists across restarts)
    blender_exe = None
    for candidate in _BLENDER_EXE_CANDIDATES:
        if os.path.isfile(candidate):
            blender_exe = candidate
            break
    if not blender_exe:
        blender_exe = shutil.which("blender")

    if blender_exe:
        print("\n  [6/6] Enabling addon in Blender preferences ...")
        enable_script = os.path.join(os.path.dirname(__file__), "_enable_addon.py")
        with open(enable_script, "w") as f:
            f.write(
                "import bpy\n"
                "bpy.ops.preferences.addon_enable(module='synthgen_mcp')\n"
                "bpy.ops.wm.save_userpref()\n"
                "print('OK  synthgen_mcp enabled')\n"
            )
        try:
            result = subprocess.run(
                [blender_exe, "--background", "--python-exit-code", "1",
                 "--python", enable_script],
                capture_output=True, text=True, timeout=60,
            )
            if "OK  synthgen_mcp enabled" in result.stdout:
                print("        Addon enabled and preferences saved")
            else:
                print("  WARN  Could not enable addon automatically")
                if result.stderr:
                    for line in result.stderr.strip().splitlines()[-3:]:
                        print(f"        {line}")
        except Exception as exc:
            print(f"  WARN  Could not run Blender to enable addon: {exc}")
        finally:
            if os.path.exists(enable_script):
                os.remove(enable_script)
    else:
        print("\n  WARN  Blender executable not found — enable the addon manually:")
        print("        Edit → Preferences → Add-ons → search 'Synthgen' → enable")

    print()
    print("DONE  Open Blender (addon auto-starts), then run:")
    print("      python tools/validate_addon.py")


if __name__ == "__main__":
    main()
