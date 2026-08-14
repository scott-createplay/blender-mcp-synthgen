"""Dependency management — install mcp SDK into the addon's vendor/ directory."""

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

_REQUIREMENTS = ["mcp[cli]>=1.3.0,<2"]


def _find_python() -> str:
    """Find Blender's bundled Python executable."""
    candidates = [
        os.path.join(sys.prefix, "bin", "python.exe"),
        os.path.join(sys.prefix, "bin", "python3.exe"),
        os.path.join(sys.prefix, "bin", "python3"),
        os.path.join(sys.prefix, "bin", "python"),
        os.path.join(sys.prefix, "python.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return sys.executable


def deps_installed() -> bool:
    """Check whether the mcp SDK is importable."""
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


def install_deps(vendor_path: str) -> None:
    """Pip-install dependencies into *vendor_path* using Blender's Python."""
    os.makedirs(vendor_path, exist_ok=True)
    python = _find_python()
    logger.info("Installing MCP SDK into %s using %s", vendor_path, python)

    cmd = [
        python, "-m", "pip", "install",
        "--target", vendor_path,
        "--upgrade",
        "--no-user",
    ] + _REQUIREMENTS

    try:
        subprocess.check_call(cmd, timeout=120)
        logger.info("Dependencies installed successfully")
    except subprocess.CalledProcessError as exc:
        logger.error("pip install failed (exit %d)", exc.returncode)
        raise RuntimeError(
            f"Failed to install MCP dependencies. "
            f"Try manually: {' '.join(cmd)}"
        ) from exc
    except FileNotFoundError:
        raise RuntimeError(
            f"Python executable not found at {python}. "
            f"Cannot install dependencies automatically."
        )
