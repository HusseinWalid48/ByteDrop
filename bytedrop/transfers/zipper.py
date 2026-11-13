"""Folder scanning, skipped-item reporting, thumbnail generation, and streaming ZIP creation."""
from __future__ import annotations

import base64
import io
import logging
import os
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from bytedrop.fsutil import ALREADY_COMPRESSED_EXTS, hide_path
from bytedrop.paths import win_long_path

logger = logging.getLogger("bytedrop.transfers.zipper")


def generate_thumbnail(file_path: Path) -> str | None:
    """Generates a small 96x96 WEBP base64 data URI thumbnail for image files."""
    if file_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        return None
    try:
        with Image.open(win_long_path(file_path)) as raw_img:
            raw_img.thumbnail((96, 96))
            out_img: Image.Image = raw_img.convert("RGB") if raw_img.mode not in ("RGB", "RGBA") else raw_img
            buf = io.BytesIO()
            out_img.save(buf, format="WEBP", quality=70)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return f"data:image/webp;base64,{b64}"
    except Exception as exc:
        logger.debug("Thumbnail generation skipped for %s: %s", file_path.name, exc)
        return None


class ZipCancelledError(Exception):
    """Raised when folder scanning or archive creation is cancelled."""


def scan_dir_stats(
    directory: Path,
    on_progress: Callable[[int, int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[int, int, int, list[str]]:
    """Scans directory recursively without following symlinks.

    Returns (total_bytes, total_files, skipped_count, first_3_skipped_reasons)
    and invokes on_progress(total_bytes, total_files, skipped_count) every ~500 ms.
    """
    if should_cancel and should_cancel():
        raise ZipCancelledError("Folder scan cancelled")

    total_bytes = 0
    total_files = 0
    skipped_count = 0
    skipped_reasons: list[str] = []
    last_report = time.monotonic()

    if on_progress:
        on_progress(0, 0, 0)

    def record_skip(reason: str) -> None:
        nonlocal skipped_count
        skipped_count += 1
        if len(skipped_reasons) < 3:
            skipped_reasons.append(reason)

    stack = [directory]
    while stack:
        if should_cancel and should_cancel():
            raise ZipCancelledError("Folder scan cancelled")
        current = stack.pop()
        try:
            with os.scandir(win_long_path(current)) as it:
                for entry in it:
                    if should_cancel and should_cancel():
                        raise ZipCancelledError("Folder scan cancelled")
                    try:
                        if entry.is_symlink():
                            record_skip(f"Symlink skipped: {entry.name}")
                            continue
                        if entry.is_file(follow_symlinks=False):
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                            total_files += 1
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError as entry_exc:
                        record_skip(f"Unreadable entry {entry.name}: {entry_exc.strerror or entry_exc}")

                    now = time.monotonic()
                    if on_progress and (now - last_report) >= 0.5:
                        last_report = now
                        on_progress(total_bytes, total_files, skipped_count)
        except OSError as dir_exc:
            record_skip(f"Unreadable folder {current.name}: {dir_exc.strerror or dir_exc}")

    return total_bytes, total_files, skipped_count, skipped_reasons


def create_streaming_zip(
    source_dir: Path,
    dest_zip_path: Path,
    max_folder_gb: int = 20,
    max_folder_files: int = 10000,
    on_progress: Callable[[int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Path:
    """Streams a directory into a ZIP64 archive using ZIP_STORED for media/archives and ZIP_DEFLATED for docs."""
    total_bytes, total_files, _skipped, _reasons = scan_dir_stats(source_dir, should_cancel=should_cancel)
    max_bytes = int(max_folder_gb * 1024 * 1024 * 1024)
    if total_bytes > max_bytes:
        raise ValueError(f"Folder exceeds max limit of {max_folder_gb} GB")
    if total_files > max_folder_files:
        raise ValueError(f"Folder exceeds max file count of {max_folder_files}")

    dest_zip_path.parent.mkdir(parents=True, exist_ok=True)
    processed_bytes = 0
    last_notify = 0.0
    if on_progress:
        on_progress(0)

    try:
        with zipfile.ZipFile(win_long_path(dest_zip_path), "w", allowZip64=True) as zf:
            for root, _, files in os.walk(win_long_path(source_dir)):
                if should_cancel and should_cancel():
                    raise ZipCancelledError("Archive creation cancelled")
                root_path = Path(root)
                for file in files:
                    if should_cancel and should_cancel():
                        raise ZipCancelledError("Archive creation cancelled")
                    full_path = root_path / file
                    try:
                        if full_path.is_symlink():
                            continue
                        rel_arcname = full_path.relative_to(win_long_path(source_dir))
                        ext = full_path.suffix.lower()
                        comp = zipfile.ZIP_STORED if ext in ALREADY_COMPRESSED_EXTS else zipfile.ZIP_DEFLATED
                        zinfo = zipfile.ZipInfo.from_file(
                            full_path,
                            arcname=str(rel_arcname),
                            strict_timestamps=False,
                        )
                        zinfo.compress_type = comp
                        with open(full_path, "rb") as src_f, zf.open(zinfo, mode="w") as dst_f:
                            while True:
                                if should_cancel and should_cancel():
                                    raise ZipCancelledError("Archive creation cancelled")
                                chunk = src_f.read(256 * 1024)
                                if not chunk:
                                    break
                                dst_f.write(chunk)
                                processed_bytes += len(chunk)
                                now = time.monotonic()
                                if on_progress and (now - last_notify) >= 0.25 and total_bytes > 0:
                                    last_notify = now
                                    pct = min(99, int((processed_bytes / total_bytes) * 100))
                                    on_progress(pct)
                    except ZipCancelledError:
                        raise
                    except OSError as exc:
                        logger.debug("Skipping unreadable file during zip %s: %s", full_path, exc)
                        continue

                    now = time.monotonic()
                    if on_progress and (now - last_notify) >= 0.25 and total_bytes > 0:
                        last_notify = now
                        pct = min(99, int((processed_bytes / total_bytes) * 100))
                        on_progress(pct)
    except BaseException:
        dest_zip_path.unlink(missing_ok=True)
        raise

    hide_path(dest_zip_path.parent)
    if on_progress:
        on_progress(100)
    return dest_zip_path
