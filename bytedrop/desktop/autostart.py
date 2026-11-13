"""Windows login auto-start registry helper (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run)."""
from __future__ import annotations

import contextlib
import importlib
import logging
import os
import sys
from typing import Any

from bytedrop.paths import get_app_dir

logger = logging.getLogger("bytedrop.desktop.autostart")


def update_windows_startup_registry(enable: bool) -> bool:
    """Adds or removes the ByteDrop entry in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""
    if os.name != "nt":
        return False
    try:
        winreg: Any = importlib.import_module("winreg")
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                exe = sys.executable
                script = str((get_app_dir() / "main.py").resolve())
                cmd = f'"{exe}" "{script}"' if not getattr(sys, "frozen", False) else f'"{exe}"'
                winreg.SetValueEx(key, "ByteDrop", 0, winreg.REG_SZ, cmd)
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, "ByteDrop")
        return True
    except Exception as exc:
        logger.warning("Failed to update Windows Run registry key: %s", exc)
        return False
