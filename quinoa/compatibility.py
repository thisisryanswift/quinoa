"""Compatibility checks for system requirements."""

import os
import shutil
import subprocess
import sys


def is_linux() -> bool:
    """Check if running on Linux."""
    return sys.platform.startswith("linux")


def is_pipewire_installed() -> bool:
    """Check if PipeWire is installed."""
    return shutil.which("pipewire") is not None


def is_pipewire_running() -> bool:
    """Check if PipeWire daemon is running."""
    # Method 1: Check for socket
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        socket_path = os.path.join(runtime_dir, "pipewire-0")
        if os.path.exists(socket_path):
            return True

    # Method 2: Check process list (fallback)
    try:
        # pgrep is widely available on Linux
        subprocess.check_call(["pgrep", "-x", "pipewire"], stdout=subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return False


def get_distro_name() -> str:
    """Get the distribution name (e.g. 'Ubuntu', 'Fedora')."""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("NAME="):
                    return line.split("=")[1].strip().strip('"')
    except Exception:
        pass
    return "Linux"
