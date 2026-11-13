"""Chunked resumable file upload handler (Phone -> PC) with atomic finalization."""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse

from bytedrop.auth import ByteDropHttpError
from bytedrop.fsutil import get_category, sanitize_filename, unique_path
from bytedrop.paths import win_long_path
from bytedrop.state import is_valid_id
from bytedrop.transfers.manager import TransferManager
from bytedrop.transfers.speed import SpeedEstimator
from bytedrop.transfers.zipper import generate_thumbnail

logger = logging.getLogger("bytedrop.transfers.upload")

MAX_CHUNK_BYTES = 32 * 1024 * 1024
CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$")


def parse_content_range_offset(content_range: str | None, fallback_offset: int | None) -> int:
    """Extracts start byte offset from Content-Range header ('bytes start-end/total') or fallback header."""
    if content_range:
        m = CONTENT_RANGE_RE.match(content_range.strip())
        if not m:
            raise ByteDropHttpError(400, "Malformed Content-Range header", "BAD_CONTENT_RANGE")
        start = int(m.group(1))
        end = int(m.group(2))
        if start < 0 or end < start:
            raise ByteDropHttpError(400, "Invalid Content-Range bounds", "BAD_CONTENT_RANGE")
        return start
    if fallback_offset is not None:
        if fallback_offset < 0:
            raise ByteDropHttpError(400, "Negative chunk offset", "BAD_UPLOAD_HEADERS")
        return int(fallback_offset)
    return 0


def _move_to_unique_path(part_path: Path, target_dir: Path, safe_name: str) -> Path:
    """Atomically reserves a collision-free destination path with 'xb' and replaces it with part_path."""
    last_exc: OSError | None = None
    for _ in range(5):
        candidate = unique_path(target_dir, safe_name)
        long_candidate = win_long_path(candidate)
        try:
            with open(long_candidate, "xb"):
                pass
        except FileExistsError as exc:
            last_exc = exc
            continue

        try:
            os.replace(win_long_path(part_path), long_candidate)
            return candidate
        except OSError:
            try:
                shutil.move(str(win_long_path(part_path)), str(long_candidate))
                return candidate
            except OSError:
                long_candidate.unlink(missing_ok=True)
                raise

    if last_exc is not None:
        raise last_exc
    raise OSError("Failed to reserve unique destination path")


class UploadHandler:
    """Executes resumable chunk writes for accepted phone_to_pc transfers."""

    def __init__(self, manager: TransferManager) -> None:
        self.manager = manager

    def get_committed_offset(self, transfer_id: str) -> int:
        if not is_valid_id(transfer_id):
            raise ByteDropHttpError(400, "Invalid transfer id", "BAD_TRANSFER_ID")
        tr = self.manager.get_transfer(transfer_id)
        if tr is None:
            raise ByteDropHttpError(404, "Transfer not found", "TRANSFER_NOT_FOUND")
        if tr.state == "done":
            return tr.file.size
        part_path = self.manager.config.partial_dir / f"{transfer_id}.part"
        return part_path.stat().st_size if part_path.exists() else 0

    def process_chunk(
        self,
        transfer_id: str,
        offset: int,
        chunk_data: bytes,
    ) -> dict[str, Any] | JSONResponse:
        if not is_valid_id(transfer_id):
            raise ByteDropHttpError(400, "Invalid transfer id", "BAD_TRANSFER_ID")
        if offset < 0:
            raise ByteDropHttpError(400, "Invalid negative offset", "BAD_OFFSET")
        if len(chunk_data) > MAX_CHUNK_BYTES:
            raise ByteDropHttpError(413, "Chunk exceeds maximum size limit", "CHUNK_TOO_LARGE")

        tr = self.manager.get_transfer(transfer_id)
        if tr is None or tr.direction != "phone_to_pc":
            raise ByteDropHttpError(404, "Transfer not found", "TRANSFER_NOT_FOUND")

        lock = self.manager.get_upload_lock(transfer_id)
        part_path = self.manager.config.partial_dir / f"{transfer_id}.part"
        declared_size = tr.file.size
        safe_name = sanitize_filename(tr.file.name)
        category = get_category(safe_name)

        with lock:
            current_size = part_path.stat().st_size if part_path.exists() else 0
            if tr.state == "paused":
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "Transfer is paused",
                        "code": "TRANSFER_PAUSED",
                        "offset": current_size,
                    },
                )
            if tr.state not in ("accepted", "active"):
                raise ByteDropHttpError(
                    409,
                    f"Transfer is in state '{tr.state}' and cannot accept chunks",
                    "INVALID_TRANSFER_STATE",
                )

            if offset == 0 and current_size == 0:
                mode = "wb"
            elif offset == current_size:
                mode = "ab"
            elif offset == 0 and current_size > 0 and declared_size == 0:
                mode = "wb"
            else:
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "Offset mismatch",
                        "code": "OFFSET_MISMATCH",
                        "offset": current_size,
                    },
                )

            now_mono = time.monotonic()
            if tr.state == "accepted":
                tr.transition_to("active")
                tr.resumed_offset = current_size
                self.manager.estimators[transfer_id] = SpeedEstimator(
                    total_bytes=declared_size,
                    initial_offset=current_size,
                    now=now_mono,
                )
            elif transfer_id not in self.manager.estimators:
                self.manager.estimators[transfer_id] = SpeedEstimator(
                    total_bytes=declared_size,
                    initial_offset=current_size,
                    now=now_mono,
                )

            try:
                with open(win_long_path(part_path), mode) as f:
                    f.write(chunk_data)
                new_size = part_path.stat().st_size
            except OSError as exc:
                import errno as _errno

                logger.error("Disk write failed for upload %s: %s", transfer_id, exc)
                is_disk_full = (
                    getattr(exc, "errno", None) == _errno.ENOSPC
                    or getattr(exc, "winerror", None) == 112
                )
                if is_disk_full and part_path.exists():
                    tr.transition_to("paused")
                else:
                    part_path.unlink(missing_ok=True)
                    tr.transition_to("failed", error="Disk full or write error on PC")
                tr.speed = 0.0
                tr.eta = None
                tr.stalled = False
                tr.waiting_for_phone = False
                self.manager.estimators.pop(transfer_id, None)
                self.manager.events.emit({"type": "transfer_updated", "transfer": tr.to_dict()})
                self.manager.events.emit({
                    "type": "ui_error",
                    "code": "DISK_FULL",
                    "message": "Disk full or write error on PC",
                })
                self.manager.emit_activity_summary(force=True)
                raise ByteDropHttpError(
                    507,
                    "Disk full or write error on PC",
                    "INSUFFICIENT_STORAGE" if is_disk_full else "DISK_FULL",
                ) from exc

            if new_size > declared_size:
                part_path.unlink(missing_ok=True)
                tr.transition_to("failed", error="Upload larger than declared size")
                self.manager.events.emit({"type": "transfer_updated", "transfer": tr.to_dict()})
                self.manager.emit_activity_summary(force=True)
                raise ByteDropHttpError(400, "Upload larger than declared size", "SIZE_EXCEEDED")

            tr.bytes_done = new_size
            tr.updated_at = time.time()
            tr.waiting_for_phone = False
            est = self.manager.estimators[transfer_id]
            done = new_size >= declared_size
            metrics = est.update(
                new_size,
                force=done,
                now=now_mono,
            )
            tr.speed = float(metrics["speed"] or 0.0)
            tr.avg_speed = float(metrics["avg_speed"] or 0.0)
            tr.eta = float(metrics["eta"]) if metrics["eta"] is not None else None
            tr.elapsed = float(metrics["elapsed"] or 0.0)
            tr.stalled = bool(metrics["stalled"])

            if done:
                target_dir = self.manager.config.upload_dir / category
                try:
                    final_path = _move_to_unique_path(part_path, target_dir, safe_name)
                except OSError as exc:
                    logger.error("Failed moving completed upload %s to %s: %s", transfer_id, target_dir, exc)
                    part_path.unlink(missing_ok=True)
                    tr.transition_to("failed", error="Disk full or write error on PC")
                    tr.speed = 0.0
                    tr.eta = None
                    tr.stalled = False
                    self.manager.estimators.pop(transfer_id, None)
                    self.manager.upload_locks.pop(transfer_id, None)
                    self.manager.events.emit({"type": "transfer_updated", "transfer": tr.to_dict()})
                    self.manager.events.emit({
                        "type": "ui_error",
                        "code": "DISK_FULL",
                        "message": "Disk full or write error on PC",
                    })
                    self.manager.emit_activity_summary(force=True)
                    raise ByteDropHttpError(507, "Disk full or write error on PC", "DISK_FULL") from exc
                thumb = generate_thumbnail(final_path)
                tr.saved_as = final_path.name
                tr.file.thumbnail = thumb
                tr.transition_to("done")
                tr.eta = 0.0
                self.manager.estimators.pop(transfer_id, None)
                self.manager.upload_locks.pop(transfer_id, None)

                hist_entry = self.manager.history.record(
                    filename=tr.saved_as,
                    category=category,
                    size=new_size,
                    direction="INCOMING",
                    duration_sec=tr.elapsed,
                    avg_speed=tr.avg_speed,
                    expected_size=declared_size,
                    state=tr.state,
                    is_folder=tr.file.is_folder,
                )
                if hist_entry is not None:
                    self.manager.events.emit({"type": "history_updated", "entry": hist_entry})

            dto = tr.to_dict()

        self.manager.events.emit({"type": "transfer_updated", "transfer": dto})
        self.manager.emit_activity_summary(force=done)
        return {
            "status": "ok",
            "transfer_id": transfer_id,
            "offset": new_size,
            "progress": dto["progress"],
            "state": dto["state"],
            "speed": dto["speed"],
            "avg_speed": dto["avg_speed"],
            "eta": dto["eta"],
            "elapsed": dto["elapsed"],
            "saved_as": dto["saved_as"],
            "category": category,
        }
