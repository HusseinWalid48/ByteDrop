"""Path resolution helpers for ByteDrop (application root, %APPDATA%, uploads, and Windows long paths)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

DEFAULT_VERSION = "v1.0.0"


def is_frozen() -> bool:
    """Returns True when running inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def get_app_dir() -> Path:
    """Returns the root directory of the ByteDrop application (or executable directory when frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_resource_dir() -> Path:
    """Returns the directory containing bundled read-only resources (ui, assets, VERSION).

    When built with PyInstaller --onefile, bundled data files are extracted at runtime
    into the temporary directory pointed to by sys._MEIPASS.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return get_app_dir()


def get_ui_dir() -> Path:
    """Returns the root ui/ directory containing desktop/, web/, and shared/."""
    return get_resource_dir() / "ui"


def get_assets_dir() -> Path:
    """Returns the assets/ directory containing icons."""
    return get_resource_dir() / "assets"


def get_version_file() -> Path:
    """Returns the path to the bundled VERSION file inside get_resource_dir()."""
    return get_resource_dir() / "VERSION"


def get_version() -> str:
    """Strictly resolves and returns 'v1.0.0' with a safe fallback if the VERSION file is missing."""
    try:
        version_path = get_version_file()
        if version_path.is_file():
            raw = version_path.read_text(encoding="utf-8", errors="ignore").strip()
            cleaned = raw.lstrip("vV").strip()
            if cleaned == "1.0.0":
                return DEFAULT_VERSION
    except Exception:
        pass
    return DEFAULT_VERSION


VERSION = get_version()


def get_appdata_dir(custom_appdata: Path | None = None) -> Path:
    """Returns %APPDATA%\\ByteDrop on Windows (or ~/.config/ByteDrop on POSIX), creating subdirectories."""
    if custom_appdata is not None:
        target = custom_appdata.resolve()
    else:
        env_override = os.environ.get("BYTEDROP_APPDATA")
        if env_override:
            target = Path(env_override).resolve()
        else:
            appdata_env = os.environ.get("APPDATA")
            if appdata_env:
                target = Path(appdata_env) / "ByteDrop"
            elif os.name == "nt":
                target = Path.home() / "AppData" / "Roaming" / "ByteDrop"
            else:
                target = Path.home() / ".config" / "ByteDrop"

    target.mkdir(parents=True, exist_ok=True)
    (target / "bin").mkdir(parents=True, exist_ok=True)
    (target / "pycache").mkdir(parents=True, exist_ok=True)
    return target


def get_default_upload_dir() -> Path:
    """Returns the default user Downloads/ByteDrop directory."""
    return Path.home() / "Downloads" / "ByteDrop"


def get_temp_zip_dir(appdata_dir: Path | None = None) -> Path:
    """Returns the temporary directory for staged/zipped folders."""
    base = appdata_dir if appdata_dir is not None else Path(tempfile.gettempdir())
    target = base / "ByteDrop_Zips"
    target.mkdir(parents=True, exist_ok=True)
    return target


def win_long_path(path: Path) -> Path:
    """Adds the Windows \\\\?\\ extended-length path prefix when needed for MAX_PATH safety."""
    resolved = path.resolve()
    if os.name == "nt":
        raw = str(resolved)
        if not raw.startswith("\\\\?\\") and len(raw) >= 240:
            if raw.startswith("\\\\"):
                return Path("\\\\?\\UNC\\" + raw.lstrip("\\"))
            return Path("\\\\?\\" + raw)
    return resolved
