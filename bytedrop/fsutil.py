"""Filesystem utilities: filename sanitization, unique path generation, and hiding generated files."""
from __future__ import annotations

import ctypes
import logging
import os
import re
from pathlib import Path

from bytedrop.paths import get_app_dir, is_frozen, win_long_path

logger = logging.getLogger("bytedrop.fsutil")

FILE_ATTRIBUTE_HIDDEN = 0x02

CATEGORY_EXTENSIONS: dict[str, list[str]] = {
    "Images": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic"],
    "Videos": [".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v"],
    "Docs": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".md", ".json", ".xml"],
    "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
}

IMAGE_EXTS = frozenset(CATEGORY_EXTENSIONS["Images"])
VIDEO_EXTS = frozenset(CATEGORY_EXTENSIONS["Videos"])
DOC_EXTS = frozenset(CATEGORY_EXTENSIONS["Docs"])
AUDIO_EXTS = frozenset(CATEGORY_EXTENSIONS["Audio"])
ARCHIVE_EXTS = frozenset(CATEGORY_EXTENSIONS["Archives"])
ALREADY_COMPRESSED_EXTS = (IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS | ARCHIVE_EXTS) - {".bmp", ".svg", ".wav"}

INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

GENERATED_DIR_NAMES = frozenset({
    "__pycache__",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".partial",
    "bin",
    "temp",
    "ByteDrop_Zips",
})

GENERATED_FILE_NAMES = frozenset({
    ".deps_installed",
    "running.pid",
    "bytedrop.log",
    "bytedrop.lock",
    "cloudflared.exe",
    "cloudflared",
})

GENERATED_SUFFIXES = frozenset({
    ".pyc",
    ".pyo",
    ".log",
    ".lock",
    ".part",
})


def get_category(filename: str) -> str:
    """Maps a filename's extension to one of Images, Videos, Docs, Audio, Archives, or Others."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return "Images"
    if ext in VIDEO_EXTS:
        return "Videos"
    if ext in DOC_EXTS:
        return "Docs"
    if ext in AUDIO_EXTS:
        return "Audio"
    if ext in ARCHIVE_EXTS:
        return "Archives"
    return "Others"


def sanitize_filename(filename: str) -> str:
    """Sanitizes untrusted filenames against path traversal, control chars, and Windows reserved names."""
    raw = str(filename).replace("\\", "/")
    name = os.path.basename(raw)
    name = INVALID_NAME_CHARS.sub("_", name).strip().rstrip(". ")
    if not name or name in {".", ".."}:
        name = "file"
    stem_upper = name.split(".")[0].upper()
    if stem_upper in RESERVED_NAMES:
        name = f"_{name}"
    if len(name) > 200:
        ext = Path(name).suffix[:20]
        stem = Path(name).stem[: 200 - len(ext)]
        name = f"{stem}{ext}"
    return name


def unique_path(target_dir: Path, name: str) -> Path:
    """Returns a collision-free Path inside target_dir by appending ' (N)' before the suffix if needed (case-insensitive check)."""
    safe_dir = win_long_path(target_dir)
    safe_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(name)

    existing_lower: set[str] = set()
    try:
        for entry in safe_dir.iterdir():
            existing_lower.add(entry.name.lower())
    except OSError as exc:
        logger.debug("Could not list target_dir %s: %s", safe_dir, exc)

    def _collides(p: Path) -> bool:
        if p.name.lower() in existing_lower or f"{p.name}.part".lower() in existing_lower:
            return True
        return p.exists()

    candidate = safe_dir / safe_name
    if not _collides(candidate):
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    counter = 1
    while True:
        candidate = safe_dir / f"{stem} ({counter}){suffix}"
        if not _collides(candidate):
            return candidate
        counter += 1


def _set_win32_hidden(path_str: str) -> bool:
    """Invokes kernel32.SetFileAttributesW(path, FILE_ATTRIBUTE_HIDDEN) when available."""
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return False
    try:
        res = windll.kernel32.SetFileAttributesW(str(path_str), FILE_ATTRIBUTE_HIDDEN)
        return bool(res)
    except Exception as exc:
        logger.debug("SetFileAttributesW failed for %s: %s", path_str, exc)
        return False


def hide_path(filepath: Path) -> bool:
    """Marks a single file or directory as hidden on Windows."""
    if not filepath.exists():
        return False
    return _set_win32_hidden(str(filepath))


def is_generated_artifact(path: Path) -> bool:
    """Returns True if path is a generated cache, venv, log, lock, pid, or bytecode artifact."""
    name = path.name
    if name in GENERATED_DIR_NAMES or name in GENERATED_FILE_NAMES:
        return True
    return path.suffix.lower() in GENERATED_SUFFIXES


def hide_generated(app_dir: Path | None = None) -> list[Path]:
    """Recursively hides generated folders/files inside app_dir without hiding source or UI assets (no-op when frozen)."""
    if is_frozen():
        return []
    root = (app_dir or get_app_dir()).resolve()
    if not root.exists():
        return []

    hidden_paths: list[Path] = []
    stack: list[Path] = [root]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    entry_path = Path(entry.path)
                    name = entry.name
                    if name in {".git", "node_modules", "src", "public"}:
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue

                    if is_dir:
                        if name in GENERATED_DIR_NAMES:
                            hide_path(entry_path)
                            hidden_paths.append(entry_path)
                            # Also hide files inside __pycache__
                            if name == "__pycache__":
                                try:
                                    for sub in entry_path.iterdir():
                                        hide_path(sub)
                                        hidden_paths.append(sub)
                                except OSError as exc:
                                    logger.debug("Failed scanning __pycache__ %s: %s", entry_path, exc)
                            elif name == ".venv":
                                stamp = entry_path / ".deps_installed"
                                if stamp.exists():
                                    hide_path(stamp)
                                    hidden_paths.append(stamp)
                        else:
                            stack.append(entry_path)
                    else:
                        if is_generated_artifact(entry_path):
                            hide_path(entry_path)
                            hidden_paths.append(entry_path)
        except OSError as exc:
            logger.debug("hide_generated scan skipped %s: %s", current, exc)

    return hidden_paths
