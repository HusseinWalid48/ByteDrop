"""Transfer and Share lifecycle manager, disk-space checker, 4 Hz activity_summary, and 15-minute request expiration."""
from __future__ import annotations

import logging
import os
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from bytedrop.auth import ByteDropHttpError
from bytedrop.config import ConfigManager
from bytedrop.events import EventBus
from bytedrop.fsutil import get_category, hide_path
from bytedrop.history import HistoryStore
from bytedrop.paths import get_temp_zip_dir
from bytedrop.state import (
    ACTIVE_TRANSFER_STATES,
    TERMINAL_TRANSFER_STATES,
    ShareEntity,
    TransferEntity,
    TransferFile,
    is_valid_id,
)
from bytedrop.transfers.speed import SpeedEstimator, format_bytes, summarize_activity
from bytedrop.transfers.zipper import (
    ZipCancelledError,
    create_streaming_zip,
    generate_thumbnail,
    scan_dir_stats,
)

logger = logging.getLogger("bytedrop.transfers.manager")

REQUEST_TTL_SECONDS = 15 * 60  # 15 minutes (Section 3.4)
SUMMARY_INTERVAL_SEC = 0.25    # ~4 Hz activity_summary broadcast while active (Section 2.2)


class TransferManager:
    """Authoritative server state for all transfers, requests, and shared PC files."""

    def __init__(
        self,
        config: ConfigManager,
        events: EventBus,
        history: HistoryStore,
    ) -> None:
        self.config = config
        self.events = events
        self.history = history
        self.temp_zip_dir = get_temp_zip_dir(config.appdata_dir)
        hide_path(self.temp_zip_dir)

        self._lock = threading.RLock()
        self.transfers: dict[str, TransferEntity] = {}
        self.requests: dict[str, list[str]] = {}  # request_id -> list[transfer_id]
        self.request_created_at: dict[str, float] = {}
        self.request_meta: dict[str, dict[str, Any]] = {}
        self.shares: dict[str, ShareEntity] = {}
        self.staged_shares: dict[str, list[ShareEntity]] = {}  # request_id -> list[ShareEntity]
        self.estimators: dict[str, SpeedEstimator] = {}
        self.upload_locks: dict[str, threading.Lock] = {}
        self.preparing_items: dict[str, dict[str, Any]] = {}  # key -> {id, request_id, share_id, name, progress}
        self.cancelled_preparations: set[str] = set()

        self._last_summary_emit: float = 0.0
        self._last_summary_state: str = "idle"
        self._prev_summary_eta: float | None = None

        self.cleanup_stale_partials()

    def is_preparation_cancelled(self, *ids: str) -> bool:
        with self._lock:
            return any(bool(i) and i in self.cancelled_preparations for i in ids)

    def _resolve_transfer(self, transfer_or_share_id: str) -> TransferEntity | None:
        with self._lock:
            tr = self.transfers.get(transfer_or_share_id)
            if tr is not None:
                return tr
            for candidate in self.transfers.values():
                if candidate.share_id == transfer_or_share_id and candidate.state not in TERMINAL_TRANSFER_STATES:
                    return candidate
            for candidate in self.transfers.values():
                if candidate.share_id == transfer_or_share_id:
                    return candidate
        return None

    def cleanup_stale_partials(self, max_age_days: int = 7) -> None:
        cutoff = time.time() - (max_age_days * 86400)
        pdir = self.config.partial_dir
        if not pdir.exists():
            return
        for part in pdir.glob("*.part"):
            try:
                if part.stat().st_mtime < cutoff:
                    part.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug("Could not unlink stale partial %s: %s", part, exc)

    def get_activity_summary(self, now_sec: float | None = None) -> dict[str, Any]:
        """Computes current activity summary across all transfers and preparing items."""
        t_now = now_sec if now_sec is not None else time.time()
        conn_lost_sec = float(getattr(self.config, "connection_lost_seconds", 15.0))
        wait_phone_sec = float(getattr(self.config, "upload_waiting_phone_seconds", 45.0))
        changed_dtos: list[dict[str, Any]] = []

        with self._lock:
            for tr in self.transfers.values():
                if tr.state == "active" and tr.bytes_done > 0:
                    last_ts = float(getattr(tr, "last_chunk_at", None) or tr.updated_at)
                    idle_sec = max(0.0, t_now - last_ts)
                    if tr.direction == "pc_to_phone" and idle_sec >= conn_lost_sec:
                        tr.transition_to("interrupted")
                        tr.speed = 0.0
                        tr.eta = None
                        tr.stalled = False
                        changed_dtos.append(tr.to_dict())
                    elif tr.direction == "phone_to_pc" and idle_sec >= wait_phone_sec and not tr.waiting_for_phone:
                        tr.waiting_for_phone = True
                        tr.speed = 0.0
                        tr.eta = None
                        tr.stalled = False
                        changed_dtos.append(tr.to_dict())

            items: list[dict[str, Any]] = [t.to_dict() for t in self.transfers.values()]
            for p in self.preparing_items.values():
                items.append({
                    "id": p["id"],
                    "request_id": p.get("request_id", ""),
                    "name": p["name"],
                    "state": "preparing",
                    "preparing": True,
                    "progress": p.get("progress", 0),
                })
            prev_eta = self._prev_summary_eta

        for dto in changed_dtos:
            self.events.emit({"type": "transfer_updated", "transfer": dto})

        summary = summarize_activity(
            items,
            now_sec=t_now,
            prev_eta=prev_eta,
            connection_lost_sec=conn_lost_sec,
            upload_waiting_phone_sec=wait_phone_sec,
        )
        with self._lock:
            self._prev_summary_eta = summary["eta_seconds"] if summary["state"] == "active" else None
        return summary

    def emit_activity_summary(self, force: bool = False) -> dict[str, Any] | None:
        """Emits activity_summary at ~4 Hz while active, plus one final idle summary when the last transfer ends."""
        now_mono = time.monotonic()
        summary = self.get_activity_summary()
        state = summary["state"]

        with self._lock:
            was_non_idle = self._last_summary_state != "idle"
            if state == "idle":
                if not was_non_idle and not force:
                    return None
                self._last_summary_state = "idle"
                self._last_summary_emit = now_mono
            else:
                if not force and (now_mono - self._last_summary_emit) < SUMMARY_INTERVAL_SEC and state == self._last_summary_state:
                    return None
                self._last_summary_state = state
                self._last_summary_emit = now_mono

        payload = {"type": "activity_summary", **summary}
        self.events.emit(payload)
        return payload

    def check_disk_space(self, required_bytes: int) -> dict[str, Any]:
        """Checks free disk space in upload_dir (Section 3.1).

        If the drive cannot be read, reports check_failed=True, free_bytes=None,
        warning='Could not check free space', and allows Accept.
        """
        upload_dir = self.config.upload_dir
        drive_label = upload_dir.drive or str(upload_dir.anchor or upload_dir)
        needed_with_margin = int(max(0, required_bytes) * 1.10)
        try:
            usage = shutil.disk_usage(upload_dir)
            free_bytes = int(usage.free)
        except OSError as exc:
            logger.warning("disk_usage check failed for %s: %s", upload_dir, exc)
            return {
                "check_failed": True,
                "insufficient_disk": False,
                "free_bytes": None,
                "required_bytes": needed_with_margin,
                "drive": drive_label,
                "warning": "Could not check free space",
            }

        insufficient = required_bytes > 0 and free_bytes < needed_with_margin
        warning_msg: str | None = None
        if insufficient:
            warning_msg = (
                f"Not enough free space on {drive_label} "
                f"(needs {format_bytes(needed_with_margin)}, free {format_bytes(free_bytes)})"
            )
        return {
            "check_failed": False,
            "insufficient_disk": insufficient,
            "free_bytes": free_bytes,
            "required_bytes": needed_with_margin,
            "drive": drive_label,
            "warning": warning_msg,
        }

    def validate_incoming_files(self, raw_files: Any) -> tuple[list[TransferFile], int]:
        """Validates incoming file list without silent truncation (Section 3.4)."""
        if not isinstance(raw_files, list) or not raw_files:
            raise ByteDropHttpError(400, "No files provided in transfer request", "NO_FILES")
        limit = self.config.max_request_files
        if len(raw_files) > limit:
            raise ByteDropHttpError(
                400,
                f"Too many files in transfer request (limit is {limit})",
                "TOO_MANY_FILES",
            )
        cleaned: list[TransferFile] = []
        bytes_sum = 0
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()[:255]
            if not name:
                continue
            raw_sz = item.get("size", 0)
            if isinstance(raw_sz, bool):
                size = 0
            else:
                try:
                    size = max(0, int(raw_sz))
                except (TypeError, ValueError):
                    size = 0
            bytes_sum += size
            cat = str(item.get("category") or get_category(name))[:32]
            thumb = item.get("thumbnail")
            if not (isinstance(thumb, str) and thumb.startswith("data:image/") and len(thumb) <= 200_000):
                thumb = None
            cleaned.append(TransferFile(name=name, size=size, category=cat, thumbnail=thumb))

        if not cleaned:
            raise ByteDropHttpError(400, "No valid files in transfer request", "NO_FILES")
        return cleaned, bytes_sum

    def create_incoming_request(
        self,
        device_id: str,
        device_name: str,
        raw_files: Any,
        request_id: str | None = None,
        auto_accept: bool = False,
        via: str = "Wi-Fi",
    ) -> dict[str, Any]:
        """Creates a phone -> PC transfer request and per-file TransferEntity objects."""
        files, internal_sum_bytes = self.validate_incoming_files(raw_files)
        disk_info = self.check_disk_space(internal_sum_bytes)
        should_auto_accept = bool(auto_accept and not disk_info["insufficient_disk"])
        initial_state = "accepted" if should_auto_accept else "pending"
        via_norm = "Cloud" if str(via).lower() == "cloud" else "Wi-Fi"

        created_transfers: list[TransferEntity] = []
        batch_size = len(files)
        now = time.time()

        with self._lock:
            req_id = request_id if (request_id and is_valid_id(request_id)) else f"req_{secrets.token_hex(6)}"
            while (
                req_id in self.requests
                or req_id in self.request_meta
                or req_id in self.staged_shares
                or req_id in self.cancelled_preparations
            ):
                req_id = f"req_{secrets.token_hex(6)}"
            t_ids: list[str] = []
            for idx, tf in enumerate(files, start=1):
                tid = f"tr_{secrets.token_hex(8)}"
                entity = TransferEntity(
                    id=tid,
                    request_id=req_id,
                    batch_index=idx,
                    batch_size=batch_size,
                    direction="phone_to_pc",
                    device_id=device_id,
                    device_name=device_name,
                    file=tf,
                    state=initial_state,
                    created_at=now,
                    updated_at=now,
                    via=via_norm,
                )
                self.transfers[tid] = entity
                t_ids.append(tid)
                created_transfers.append(entity)

            self.requests[req_id] = t_ids
            self.request_created_at[req_id] = now
            self.request_meta[req_id] = {
                "request_id": req_id,
                "direction": "phone_to_pc",
                "target": "pc",
                "device_id": device_id,
                "device_name": device_name,
                "via": via_norm,
                "state": initial_state,
                "file_count": batch_size,
                "disk_check": disk_info,
                "files": [t.file.to_dict() for t in created_transfers],
                "transfer_ids": t_ids,
                "transfers": [t.to_dict() for t in created_transfers],
            }

        event_payload = {
            "type": "transfer_accepted" if should_auto_accept else "transfer_request",
            "target": "mobile" if should_auto_accept else "pc",
            "direction": "phone_to_pc",
            "request_id": req_id,
            "device_id": device_id,
            "device_name": device_name,
            "via": via_norm,
            "auto_accepted": should_auto_accept,
            "file_count": batch_size,
            "disk_check": disk_info,
            "files": [t.file.to_dict() for t in created_transfers],
            "transfers": [t.to_dict() for t in created_transfers],
        }
        self.events.emit(event_payload)
        return event_payload

    def prepare_pc_path(self, filepath: str, request_id: str = "") -> tuple[ShareEntity | None, dict[str, Any] | None]:
        """Scans a PC file or directory and returns (ShareEntity, None) or (None, rejection_dict)."""
        raw_name = os.path.basename(str(filepath).rstrip("\\/")) or str(filepath)
        try:
            path = Path(filepath).resolve()
        except Exception as exc:
            return None, {"name": raw_name, "reason_code": "INVALID_PATH", "detail": str(exc)}

        try:
            exists = path.exists()
        except OSError as exc:
            return None, {"name": raw_name, "reason_code": "PERMISSION_DENIED", "detail": str(exc)}

        if not exists:
            return None, {"name": raw_name, "reason_code": "NOT_FOUND", "detail": f"Path not found: {raw_name}"}

        share_id = f"sh_{secrets.token_hex(8)}"
        now = time.time()

        try:
            if path.is_dir():
                display_name = f"{path.name}.zip"
                prep_key = request_id or share_id
                with self._lock:
                    if self.is_preparation_cancelled(request_id, share_id):
                        return None, None
                    self.preparing_items[prep_key] = {
                        "id": share_id,
                        "request_id": request_id,
                        "share_id": share_id,
                        "name": display_name,
                        "progress": 0,
                    }
                self.emit_activity_summary(force=True)

                def on_scan_progress(b_count: int, f_count: int, s_count: int) -> None:
                    self.events.emit({
                        "type": "scan_progress",
                        "request_id": request_id,
                        "share_id": share_id,
                        "name": path.name,
                        "bytes": b_count,
                        "files": f_count,
                        "skipped_count": s_count,
                    })

                try:
                    true_size, file_count, skipped_count, skipped_reasons = scan_dir_stats(
                        path,
                        on_progress=on_scan_progress,
                        should_cancel=lambda: self.is_preparation_cancelled(request_id, share_id, prep_key),
                    )
                except ZipCancelledError:
                    logger.info("Folder scan cancelled for %s", path.name)
                    return None, None
                finally:
                    with self._lock:
                        self.preparing_items.pop(prep_key, None)
                    self.emit_activity_summary(force=True)

                if self.is_preparation_cancelled(request_id, share_id, prep_key):
                    return None, None

                max_bytes = int(self.config.max_folder_gb * 1024 * 1024 * 1024)
                if true_size > max_bytes:
                    gb_val = true_size / (1024 ** 3)
                    detail = f"Folder '{path.name}' exceeds {self.config.max_folder_gb} GB limit ({gb_val:.1f} GB)"
                    return None, {"name": path.name, "reason_code": "MAX_SIZE_EXCEEDED", "detail": detail}
                if file_count > self.config.max_folder_files:
                    detail = f"Folder '{path.name}' exceeds {self.config.max_folder_files} files limit ({file_count} files)"
                    return None, {"name": path.name, "reason_code": "MAX_FILES_EXCEEDED", "detail": detail}

                # F3: Never expose uncompressed folder size as the share size; size is 0 until zipped
                return ShareEntity(
                    id=share_id,
                    request_id=request_id,
                    file_index=0,
                    path=path,
                    name=display_name,
                    size=0,
                    uncompressed_size=true_size,
                    category="Archives",
                    is_dir=True,
                    archive_ready=False,
                    skipped_count=skipped_count,
                    skipped_reasons=skipped_reasons,
                    thumbnail=None,
                    created_at=now,
                    committed=False,
                ), None

            if path.is_file():
                display_name = path.name
                category = get_category(display_name)
                true_size = path.stat().st_size
                return ShareEntity(
                    id=share_id,
                    request_id=request_id,
                    file_index=0,
                    path=path,
                    name=display_name,
                    size=true_size,
                    uncompressed_size=true_size,
                    category=category,
                    is_dir=False,
                    archive_ready=True,
                    skipped_count=0,
                    skipped_reasons=[],
                    thumbnail=None,
                    created_at=now,
                    committed=False,
                ), None
        except PermissionError as exc:
            return None, {"name": path.name, "reason_code": "PERMISSION_DENIED", "detail": f"Permission denied: {exc}"}
        except OSError as exc:
            return None, {"name": path.name, "reason_code": "OS_ERROR", "detail": str(exc)}

        return None, {"name": raw_name, "reason_code": "UNSUPPORTED_TYPE", "detail": "Unsupported filesystem entry"}

    def stage_pc_paths(self, paths: list[str]) -> dict[str, Any]:
        """Stages PC files/folders for sharing to connected phones and emits transfer_request."""
        self.purge_expired()
        req_id = f"req_{secrets.token_hex(6)}"
        self.events.emit({"type": "scan_started", "request_id": req_id})

        staged: list[ShareEntity] = []
        rejected: list[dict[str, Any]] = []
        skipped_total = 0
        skipped_reasons: list[str] = []

        for raw_p in paths:
            if self.is_preparation_cancelled(req_id):
                break
            share, rej = self.prepare_pc_path(raw_p, request_id=req_id)
            if self.is_preparation_cancelled(req_id):
                break
            if rej is not None:
                rejected.append(rej)
                continue
            if share is not None:
                idx = len(staged)
                share.request_id = req_id
                share.file_index = idx
                staged.append(share)
                skipped_total += share.skipped_count
                for r in share.skipped_reasons:
                    if len(skipped_reasons) < 3:
                        skipped_reasons.append(r)

        if self.is_preparation_cancelled(req_id):
            return {
                "request_id": "",
                "queued": [],
                "rejected": rejected,
                "file_count": 0,
                "skipped_count": 0,
                "skipped_reasons": [],
                "transfers": [],
            }

        created_transfers: list[TransferEntity] = []
        now = time.time()
        batch_size = len(staged)

        with self._lock:
            if staged:
                self.staged_shares[req_id] = staged
                self.request_created_at[req_id] = now
                t_ids: list[str] = []
                for idx, sh in enumerate(staged, start=1):
                    tid = f"tr_{secrets.token_hex(8)}"
                    entity = TransferEntity(
                        id=tid,
                        request_id=req_id,
                        batch_index=idx,
                        batch_size=batch_size,
                        direction="pc_to_phone",
                        device_id="pc",
                        device_name="PC",
                        file=TransferFile(
                            name=sh.name,
                            size=0 if sh.is_dir else sh.size,
                            category=sh.category,
                            is_folder=sh.is_dir,
                        ),
                        state="pending",
                        created_at=now,
                        updated_at=now,
                        share_id=sh.id,
                    )
                    self.transfers[tid] = entity
                    t_ids.append(tid)
                    created_transfers.append(entity)
                self.requests[req_id] = t_ids

        queued_dicts = [s.to_dict() for s in staged]
        result = {
            "request_id": req_id if staged else "",
            "queued": queued_dicts,
            "rejected": rejected,
            "file_count": len(queued_dicts),
            "skipped_count": skipped_total,
            "skipped_reasons": skipped_reasons,
            "transfers": [t.to_dict() for t in created_transfers],
        }

        self.events.emit({
            "type": "stage_result",
            "request_id": result["request_id"],
            "queued": queued_dicts,
            "rejected": rejected,
            "skipped_count": skipped_total,
            "skipped_reasons": skipped_reasons,
        })

        if staged:
            self.events.emit({
                "type": "transfer_request",
                "target": "mobile",
                "direction": "pc_to_phone",
                "request_id": req_id,
                "file_count": len(queued_dicts),
                "skipped_count": skipped_total,
                "skipped_reasons": skipped_reasons,
                "files": queued_dicts,
                "transfers": [t.to_dict() for t in created_transfers],
            })

        return result

    def accept_request(
        self,
        request_id: str,
        accepting_device_id: str = "pc",
        by_pc: bool = False,
    ) -> dict[str, Any] | None:
        """Accepts a pending transfer request (either phone_to_pc on PC, or pc_to_phone on phone)."""
        if not is_valid_id(request_id) or self.is_preparation_cancelled(request_id):
            return None

        with self._lock:
            if request_id not in self.staged_shares and not by_pc:
                return None
            staged_list = self.staged_shares.pop(request_id, None)
            t_ids = self.requests.get(request_id, [])

        # Case 1: PC -> Phone share accepted by phone
        if staged_list is not None:
            committed_shares: list[dict[str, Any]] = []
            for sh in staged_list:
                if self.is_preparation_cancelled(request_id, sh.id):
                    return None
                if sh.is_dir:
                    zip_path = self.temp_zip_dir / f"{sh.name[:-4]}_{secrets.token_hex(4)}.zip"
                    prep_key = sh.id
                    with self._lock:
                        self.preparing_items[prep_key] = {
                            "id": sh.id,
                            "request_id": request_id,
                            "share_id": sh.id,
                            "name": sh.name,
                            "progress": 0,
                        }
                    self.emit_activity_summary(force=True)

                    def on_zip_pct(pct: int, name: str = sh.name, sid: str = sh.id, rid: str = request_id) -> None:
                        with self._lock:
                            if sid in self.preparing_items:
                                self.preparing_items[sid]["progress"] = pct
                        self.events.emit({
                            "type": "zip_progress",
                            "id": sid,
                            "share_id": sid,
                            "request_id": rid,
                            "name": name,
                            "filename": name,
                            "progress": pct,
                        })
                        self.emit_activity_summary()

                    cur_share_id = sh.id

                    def check_cancel(sid: str = cur_share_id, rid: str = request_id) -> bool:
                        return self.is_preparation_cancelled(rid, sid)

                    try:
                        create_streaming_zip(
                            sh.path,
                            zip_path,
                            max_folder_gb=self.config.max_folder_gb,
                            max_folder_files=self.config.max_folder_files,
                            on_progress=on_zip_pct,
                            should_cancel=check_cancel,
                        )
                    except ZipCancelledError:
                        logger.info("Archive creation cancelled for %s (%s)", sh.name, sh.id)
                        zip_path.unlink(missing_ok=True)
                        with self._lock:
                            for tid in t_ids:
                                tr = self.transfers.get(tid)
                                if tr and tr.state not in TERMINAL_TRANSFER_STATES:
                                    tr.transition_to("cancelled")
                        self.emit_activity_summary(force=True)
                        return None
                    except OSError as exc:
                        logger.error("Failed creating zip archive for %s (%s): %s", sh.name, sh.id, exc)
                        zip_path.unlink(missing_ok=True)
                        failed_dtos: list[dict[str, Any]] = []
                        with self._lock:
                            for tid in t_ids:
                                tr = self.transfers.get(tid)
                                if tr and tr.state not in TERMINAL_TRANSFER_STATES:
                                    tr.transition_to("failed", error="Disk full or archive write error on PC")
                                    tr.speed = 0.0
                                    tr.eta = None
                                    failed_dtos.append(tr.to_dict())
                        for f_dto in failed_dtos:
                            self.events.emit({"type": "transfer_updated", "transfer": f_dto})
                        self.events.emit({
                            "type": "ui_error",
                            "code": "DISK_FULL",
                            "message": "Disk full or archive write error on PC",
                        })
                        self.emit_activity_summary(force=True)
                        return None
                    finally:
                        with self._lock:
                            self.preparing_items.pop(prep_key, None)

                    if self.is_preparation_cancelled(request_id, sh.id):
                        zip_path.unlink(missing_ok=True)
                        self.emit_activity_summary(force=True)
                        return None

                    sh.path = zip_path
                    sh.size = zip_path.stat().st_size
                    sh.archive_ready = True
                    self.events.emit({
                        "type": "size_updated",
                        "id": sh.id,
                        "share_id": sh.id,
                        "request_id": request_id,
                        "file_index": sh.file_index,
                        "name": sh.name,
                        "size": sh.size,
                        "is_folder": True,
                    })
                else:
                    sh.thumbnail = generate_thumbnail(sh.path)

                sh.committed = True
                sh.target_device_id = accepting_device_id
                sh.created_at = time.time()
                with self._lock:
                    self.shares[sh.id] = sh
                committed_shares.append(sh.to_dict())

            with self._lock:
                self.request_created_at.pop(request_id, None)
                updated_transfers = []
                for tid in t_ids:
                    tr = self.transfers.get(tid)
                    if tr:
                        tr.device_id = accepting_device_id
                        tr.transition_to("accepted")
                        if tr.share_id and tr.share_id in self.shares:
                            tr.file.size = self.shares[tr.share_id].size
                        updated_transfers.append(tr.to_dict())

            payload = {
                "type": "transfer_accepted",
                "target": "pc",
                "direction": "pc_to_phone",
                "request_id": request_id,
                "accepted_by_device_id": accepting_device_id,
                "files": committed_shares,
                "shares": self.list_shares(),
                "transfers": updated_transfers,
            }
            self.events.emit(payload)
            self.emit_activity_summary(force=True)
            return payload

        # Case 2: Phone -> PC upload request accepted by PC
        with self._lock:
            if not t_ids:
                return None
            updated_transfers = []
            device_id = "mobile"
            for tid in t_ids:
                tr = self.transfers.get(tid)
                if tr and tr.state == "pending":
                    tr.transition_to("accepted")
                    device_id = tr.device_id
                    updated_transfers.append(tr.to_dict())
            self.request_created_at.pop(request_id, None)
            if request_id in self.request_meta:
                self.request_meta[request_id]["state"] = "accepted"

        if not updated_transfers:
            return None

        payload = {
            "type": "transfer_accepted",
            "target": "mobile",
            "direction": "phone_to_pc",
            "request_id": request_id,
            "device_id": device_id,
            "transfers": updated_transfers,
        }
        self.events.emit(payload)
        return payload

    def reject_request(
        self,
        request_id: str,
        rejected_by: str = "pc",
        by_pc: bool = False,
    ) -> dict[str, Any] | None:
        if not is_valid_id(request_id):
            return None
        with self._lock:
            if not by_pc and request_id not in self.staged_shares:
                return None
            self.cancelled_preparations.add(request_id)
            staged_list = self.staged_shares.pop(request_id, [])
            t_ids = self.requests.pop(request_id, [])
            self.request_created_at.pop(request_id, None)
            self.request_meta.pop(request_id, None)
            self.preparing_items.pop(request_id, None)
            for sh in staged_list:
                self.cancelled_preparations.add(sh.id)
                self.preparing_items.pop(sh.id, None)
            for p_key, p_val in list(self.preparing_items.items()):
                if p_val.get("request_id") == request_id:
                    self.cancelled_preparations.add(str(p_val.get("id") or ""))
                    self.preparing_items.pop(p_key, None)
            rejected_transfers = []
            direction = "pc_to_phone" if staged_list else "phone_to_pc"
            for tid in t_ids:
                tr = self.transfers.get(tid)
                if tr and tr.state in ACTIVE_TRANSFER_STATES:
                    if tr.share_id:
                        self.cancelled_preparations.add(tr.share_id)
                        self.preparing_items.pop(tr.share_id, None)
                    tr.transition_to("rejected")
                    rejected_transfers.append(tr.to_dict())

        for sh in staged_list:
            if sh.path.exists() and self.temp_zip_dir.resolve() in sh.path.resolve().parents:
                sh.path.unlink(missing_ok=True)

        payload = {
            "type": "transfer_rejected",
            "target": "pc" if direction == "pc_to_phone" else "mobile",
            "direction": direction,
            "request_id": request_id,
            "rejected_by": rejected_by,
            "files": [s.to_dict() for s in staged_list] if staged_list else [t["file"] for t in rejected_transfers],
            "transfers": rejected_transfers,
        }
        self.events.emit(payload)
        self.emit_activity_summary(force=True)
        return payload

    def cancel_preparation(self, target_id: str, cancelled_by: str = "pc") -> dict[str, Any] | None:
        """Cancels an in-progress folder scan or archive zipping operation by request_id, share_id, or transfer_id."""
        if not is_valid_id(target_id):
            return None

        matched_req_id = ""
        matched_share_id = ""
        matched_name = "Archive.zip"
        cancelled_dtos: list[dict[str, Any]] = []

        with self._lock:
            self.cancelled_preparations.add(target_id)

            # 1. Check preparing_items
            for p_key, p_val in list(self.preparing_items.items()):
                pid = str(p_val.get("id") or "")
                pshare = str(p_val.get("share_id") or "")
                preq = str(p_val.get("request_id") or "")
                if target_id in (p_key, pid, pshare, preq):
                    matched_name = str(p_val.get("name") or matched_name)
                    if preq:
                        matched_req_id = preq
                        self.cancelled_preparations.add(preq)
                    if pshare:
                        matched_share_id = pshare
                        self.cancelled_preparations.add(pshare)
                    if pid:
                        self.cancelled_preparations.add(pid)
                    self.preparing_items.pop(p_key, None)

            # 2. Check staged_shares
            for rid, sh_list in list(self.staged_shares.items()):
                if rid in (target_id, matched_req_id) or any(s.id == target_id for s in sh_list):
                    matched_req_id = rid
                    self.cancelled_preparations.add(rid)
                    for s in sh_list:
                        self.cancelled_preparations.add(s.id)
                        self.preparing_items.pop(s.id, None)
                        if not matched_share_id:
                            matched_share_id = s.id
                        matched_name = s.name
                    self.staged_shares.pop(rid, None)

            # 3. Check transfers matching target_id, matched_req_id, or matched_share_id
            for tid, tr in list(self.transfers.items()):
                if (
                    tid == target_id
                    or (matched_req_id and tr.request_id == matched_req_id)
                    or (tr.request_id == target_id)
                    or (tr.share_id and tr.share_id in (target_id, matched_share_id))
                ):
                    if tr.request_id:
                        matched_req_id = matched_req_id or tr.request_id
                        self.cancelled_preparations.add(tr.request_id)
                    if tr.share_id:
                        matched_share_id = matched_share_id or tr.share_id
                        self.cancelled_preparations.add(tr.share_id)
                        self.preparing_items.pop(tr.share_id, None)
                    matched_name = tr.file.name or matched_name
                    if tr.state not in TERMINAL_TRANSFER_STATES:
                        tr.transition_to("cancelled")
                        self.estimators.pop(tid, None)
                        self.upload_locks.pop(tid, None)
                        cancelled_dtos.append(tr.to_dict())

            if matched_req_id:
                self.requests.pop(matched_req_id, None)
                self.request_created_at.pop(matched_req_id, None)
                self.request_meta.pop(matched_req_id, None)
                self.preparing_items.pop(matched_req_id, None)

        payload: dict[str, Any] = {
            "type": "transfer_cancelled",
            "id": matched_share_id or matched_req_id or target_id,
            "transfer_id": cancelled_dtos[0]["id"] if cancelled_dtos else target_id,
            "share_id": matched_share_id or target_id,
            "request_id": matched_req_id or target_id,
            "name": matched_name,
            "filename": matched_name,
            "cancelled_by": cancelled_by,
            "transfer": cancelled_dtos[0] if cancelled_dtos else None,
        }
        self.events.emit(payload)
        self.emit_activity_summary(force=True)
        return payload

    @staticmethod
    def _is_pc_actor(actor: str | None) -> bool:
        return actor is None or actor == "pc"

    def _actor_owns_prep_or_request_locked(self, target_id: str, actor: str | None) -> bool:
        if self._is_pc_actor(actor):
            return True
        if target_id in self.requests:
            tids = self.requests.get(target_id, [])
            trs = [self.transfers[tid] for tid in tids if tid in self.transfers]
            return bool(trs) and all(tr.device_id == actor for tr in trs)
        sh = self.shares.get(target_id)
        if sh is not None:
            return sh.target_device_id == actor
        tr = self._resolve_transfer(target_id)
        if tr is not None:
            return tr.device_id == actor
        for p in self.preparing_items.values():
            req_id = str(p.get("request_id") or "")
            if target_id in (p.get("id"), p.get("share_id"), req_id) and req_id in self.requests:
                tids = self.requests.get(req_id, [])
                trs = [self.transfers[tid] for tid in tids if tid in self.transfers]
                return bool(trs) and all(tr.device_id == actor for tr in trs)
        return False

    def cancel_any(
        self,
        target_id: str,
        cancelled_by: str = "pc",
        actor: str | None = None,
    ) -> dict[str, Any] | None:
        """Cancels an active transfer, a folder preparation, or a pending request by ID."""
        if not is_valid_id(target_id):
            return None
        with self._lock:
            is_prep = (
                target_id in self.preparing_items
                or any(
                    target_id in (p.get("id"), p.get("share_id"), p.get("request_id"))
                    for p in self.preparing_items.values()
                )
                or target_id in self.staged_shares
                or target_id in self.requests
            )
            tr = self._resolve_transfer(target_id)
            if not self._is_pc_actor(actor):
                if tr is not None and tr.device_id != actor:
                    return None
                if is_prep and not self._actor_owns_prep_or_request_locked(target_id, actor):
                    return None
        if is_prep:
            return self.cancel_preparation(target_id, cancelled_by=cancelled_by)
        dto = self.cancel_transfer(target_id, cancelled_by=cancelled_by, actor=actor)
        if dto is not None:
            return dto
        with self._lock:
            if tr is not None:
                return None
            if not self._is_pc_actor(actor) and not self._actor_owns_prep_or_request_locked(target_id, actor):
                return None
        return self.cancel_preparation(target_id, cancelled_by=cancelled_by)

    def pause_transfer(self, transfer_id: str, actor: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            tr = self._resolve_transfer(transfer_id)
            if not tr or not tr.can_transition_to("paused"):
                return None
            if not self._is_pc_actor(actor) and tr.device_id != actor:
                return None
            tr.transition_to("paused")
            est = self.estimators.get(tr.id)
            if est:
                est.pause()
                snap = est.snapshot()
                tr.speed = float(snap["speed"] or 0.0)
            else:
                tr.speed = 0.0
            tr.eta = None
            tr.stalled = False
            dto = tr.to_dict()
        self.events.emit({"type": "transfer_updated", "transfer": dto})
        self.emit_activity_summary(force=True)
        return dto

    def resume_transfer(self, transfer_id: str, actor: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            tr = self._resolve_transfer(transfer_id)
            if not tr or tr.state not in ("paused", "interrupted"):
                return None
            if not self._is_pc_actor(actor) and tr.device_id != actor:
                return None
            tr.transition_to("active")
            est = self.estimators.get(tr.id)
            if est:
                est.resume()
            dto = tr.to_dict()
        self.events.emit({"type": "transfer_updated", "transfer": dto})
        self.emit_activity_summary(force=True)
        return dto

    def cancel_transfer(
        self,
        transfer_id: str,
        cancelled_by: str = "pc",
        actor: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            tr = self._resolve_transfer(transfer_id)
            if not tr or tr.state in TERMINAL_TRANSFER_STATES:
                return None
            if not self._is_pc_actor(actor) and tr.device_id != actor:
                return None
            canonical_id = tr.id
            tr.transition_to("cancelled")
            tr.speed = 0.0
            tr.eta = None
            tr.stalled = False
            self.estimators.pop(canonical_id, None)
            self.upload_locks.pop(canonical_id, None)
            if tr.share_id:
                self.cancelled_preparations.add(tr.share_id)
                self.preparing_items.pop(tr.share_id, None)
                if tr.share_id in self.shares:
                    self.shares[tr.share_id].auto_download_allowed = False
            dto = tr.to_dict()

        part_path = self.config.partial_dir / f"{canonical_id}.part"
        part_path.unlink(missing_ok=True)
        self.events.emit({
            "type": "transfer_cancelled",
            "id": canonical_id,
            "transfer_id": canonical_id,
            "share_id": tr.share_id,
            "request_id": tr.request_id,
            "filename": tr.file.name,
            "name": tr.file.name,
            "cancelled_by": cancelled_by,
            "transfer": dto,
        })
        self.emit_activity_summary(force=True)
        return dto

    def cancel_all_transfers(self, device_id: str | None = None, cancelled_by: str = "pc") -> dict[str, Any]:
        """Cancels every non-terminal transfer and active preparation (G3)."""
        is_pc = self._is_pc_actor(device_id)
        with self._lock:
            if is_pc:
                prep_ids = [
                    str(p.get("id") or p_key)
                    for p_key, p in self.preparing_items.items()
                ]
                staged_req_ids = list(self.staged_shares.keys())
            else:
                prep_ids = [
                    str(p.get("id") or p_key)
                    for p_key, p in self.preparing_items.items()
                    if self._actor_owns_prep_or_request_locked(str(p.get("id") or p_key), device_id)
                ]
                staged_req_ids = []
            target_tids = [
                tid
                for tid, tr in self.transfers.items()
                if tr.state not in TERMINAL_TRANSFER_STATES
                and (is_pc or tr.device_id == device_id)
            ]

        cancelled_ids: list[str] = []
        for pid in prep_ids:
            res = self.cancel_preparation(pid, cancelled_by=cancelled_by)
            if res is not None:
                cancelled_ids.append(pid)
        for srid in staged_req_ids:
            if srid not in cancelled_ids:
                res = self.cancel_preparation(srid, cancelled_by=cancelled_by)
                if res is not None:
                    cancelled_ids.append(srid)
        for tid in target_tids:
            dto = self.cancel_transfer(tid, cancelled_by=cancelled_by, actor=device_id)
            if dto is not None:
                cancelled_ids.append(tid)

        payload = {
            "type": "transfers_cancelled_all",
            "cancelled_by": cancelled_by,
            "cancelled_ids": cancelled_ids,
            "count": len(cancelled_ids),
        }
        self.events.emit(payload)
        self.emit_activity_summary(force=True)
        return payload

    def cancel_device_transfers(self, device_id: str) -> list[str]:
        """Cancels all active/pending transfers for a kicked device and disables auto-download on its shares."""
        cancelled_ids: list[str] = []
        with self._lock:
            for tid, tr in list(self.transfers.items()):
                if tr.device_id == device_id and tr.state in ACTIVE_TRANSFER_STATES:
                    tr.transition_to("cancelled", error="Device disconnected by PC")
                    tr.speed = 0.0
                    tr.eta = None
                    self.estimators.pop(tid, None)
                    self.upload_locks.pop(tid, None)
                    cancelled_ids.append(tid)
            for sh in self.shares.values():
                if sh.target_device_id == device_id:
                    sh.auto_download_allowed = False

        for tid in cancelled_ids:
            part = self.config.partial_dir / f"{tid}.part"
            part.unlink(missing_ok=True)
            with self._lock:
                dto = self.transfers[tid].to_dict()
            self.events.emit({
                "type": "transfer_cancelled",
                "id": tid,
                "transfer_id": tid,
                "filename": dto["file"]["name"],
                "name": dto["file"]["name"],
                "cancelled_by": "pc",
                "transfer": dto,
            })
        if cancelled_ids:
            self.emit_activity_summary(force=True)
        return cancelled_ids

    def remove_share(self, share_id: str, actor: str | None = None) -> bool:
        active_tids: list[str] = []
        with self._lock:
            existing_sh = self.shares.get(share_id)
            if not self._is_pc_actor(actor) and (existing_sh is None or existing_sh.target_device_id != actor):
                return False
            self.cancelled_preparations.add(share_id)
            sh = self.shares.pop(share_id, None)
            self.preparing_items.pop(share_id, None)
            for tid, tr in self.transfers.items():
                if tr.share_id == share_id and tr.state not in TERMINAL_TRANSFER_STATES:
                    active_tids.append(tid)
        for tid in active_tids:
            self.cancel_transfer(tid, actor=actor)
        if not sh:
            return False
        if sh.path.exists() and self.temp_zip_dir.resolve() in sh.path.resolve().parents:
            try:
                sh.path.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug("Failed unlinking temp zip %s: %s", sh.path, exc)
        self.events.emit({"type": "share_removed", "share_id": share_id, "shares": self.list_shares()})
        self.emit_activity_summary(force=True)
        return True

    def clear_all_staged(self) -> None:
        with self._lock:
            req_ids = list(self.request_created_at.keys())
            prep_keys = list(self.preparing_items.keys())
            active_tids = [
                tid for tid, tr in self.transfers.items() if tr.state in ACTIVE_TRANSFER_STATES
            ]
        for p_key in prep_keys:
            self.cancel_preparation(p_key)
        for rid in req_ids:
            self.expire_request(rid)
        for tid in active_tids:
            self.cancel_transfer(tid)

    def expire_request(self, request_id: str) -> bool:
        with self._lock:
            self.cancelled_preparations.add(request_id)
            staged_list = self.staged_shares.pop(request_id, [])
            t_ids = self.requests.pop(request_id, [])
            self.request_created_at.pop(request_id, None)
            self.request_meta.pop(request_id, None)
            self.preparing_items.pop(request_id, None)
            for sh in staged_list:
                self.cancelled_preparations.add(sh.id)
                self.preparing_items.pop(sh.id, None)
            expired_transfers = []
            for tid in t_ids:
                tr = self.transfers.get(tid)
                if tr and tr.state in ("pending", "accepted"):
                    tr.transition_to("expired", error="Request expired after 15 minutes")
                    expired_transfers.append(tr.to_dict())

        for sh in staged_list:
            if sh.path.exists() and self.temp_zip_dir.resolve() in sh.path.resolve().parents:
                sh.path.unlink(missing_ok=True)

        if expired_transfers or staged_list:
            self.events.emit({
                "type": "transfer_expired",
                "request_id": request_id,
                "transfers": expired_transfers,
            })
            self.emit_activity_summary(force=True)
            return True
        return False

    def purge_expired(self, now: float | None = None) -> list[str]:
        """Purges pending requests (>15m), waiting rows (>waiting_ttl_minutes), interrupted transfers (>interrupted_timeout_seconds), and old shares."""
        t = now if now is not None else time.time()
        self.get_activity_summary(now_sec=t)
        expired_reqs: list[str] = []
        with self._lock:
            for req_id, created in list(self.request_created_at.items()):
                if (t - created) >= REQUEST_TTL_SECONDS:
                    expired_reqs.append(req_id)

        for req_id in expired_reqs:
            self.expire_request(req_id)

        # G2: Expire waiting transfers that never received their first byte within waiting_ttl_minutes
        waiting_ttl_sec = float(self.config.waiting_ttl_minutes * 60)
        # G4: Expire interrupted transfers older than interrupted_timeout_seconds
        interrupted_ttl_sec = float(self.config.interrupted_timeout_seconds)

        waiting_expired_dtos: list[dict[str, Any]] = []
        interrupted_expired_dtos: list[dict[str, Any]] = []

        with self._lock:
            for tid, tr in list(self.transfers.items()):
                if tr.state in ("accepted", "active") and tr.bytes_done == 0:
                    ref_time = tr.updated_at or tr.created_at
                    if (t - ref_time) >= waiting_ttl_sec:
                        tr.transition_to("expired", error="Transfer expired: the phone did not start downloading")
                        tr.speed = 0.0
                        tr.eta = None
                        self.estimators.pop(tid, None)
                        self.upload_locks.pop(tid, None)
                        waiting_expired_dtos.append(tr.to_dict())
                        expired_reqs.append(tid)
                elif tr.state == "interrupted":
                    ref_time = tr.interrupted_at or tr.updated_at
                    if (t - ref_time) >= interrupted_ttl_sec:
                        tr.transition_to("expired", error="Interrupted transfer timed out")
                        tr.speed = 0.0
                        tr.eta = None
                        self.estimators.pop(tid, None)
                        self.upload_locks.pop(tid, None)
                        interrupted_expired_dtos.append(tr.to_dict())
                        expired_reqs.append(tid)

        for dto in waiting_expired_dtos:
            part_path = self.config.partial_dir / f"{dto['id']}.part"
            part_path.unlink(missing_ok=True)
            self.events.emit({
                "type": "transfer_expired",
                "reason": "waiting_timeout",
                "transfer_id": dto["id"],
                "share_id": dto.get("share_id"),
                "request_id": dto["request_id"],
                "transfers": [dto],
            })

        for dto in interrupted_expired_dtos:
            part_path = self.config.partial_dir / f"{dto['id']}.part"
            part_path.unlink(missing_ok=True)
            self.events.emit({
                "type": "transfer_expired",
                "reason": "interrupted_timeout",
                "transfer_id": dto["id"],
                "share_id": dto.get("share_id"),
                "request_id": dto["request_id"],
                "transfers": [dto],
            })

        if waiting_expired_dtos or interrupted_expired_dtos:
            self.emit_activity_summary(force=True)

        ttl_sec = self.config.shared_ttl_hours * 3600
        expired_shares: list[str] = []
        with self._lock:
            for sid, sh in list(self.shares.items()):
                if (t - sh.created_at) >= ttl_sec:
                    expired_shares.append(sid)

        for sid in expired_shares:
            self.remove_share(sid)

        # 3.2: Prune terminal transfers older than 1 hour, orphaned requests, and cap cancelled_preparations
        terminal_retention_sec = 3600.0
        with self._lock:
            for tid, tr in list(self.transfers.items()):
                if tr.state in TERMINAL_TRANSFER_STATES:
                    ended_at = tr.updated_at or tr.completed_at or tr.created_at
                    if (t - ended_at) >= terminal_retention_sec:
                        self.transfers.pop(tid, None)
                        self.estimators.pop(tid, None)
                        self.upload_locks.pop(tid, None)

            for req_id, tids in list(self.requests.items()):
                if req_id in self.staged_shares:
                    continue
                if not any(tid in self.transfers for tid in tids):
                    self.requests.pop(req_id, None)
                    self.request_meta.pop(req_id, None)
                    self.request_created_at.pop(req_id, None)

            while len(self.cancelled_preparations) > 2048:
                self.cancelled_preparations.pop()

        return expired_reqs

    def list_transfers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [t.to_dict() for t in self.transfers.values()]

    def list_preparing(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(p) for p in self.preparing_items.values()]

    def list_shares(self) -> list[dict[str, Any]]:
        with self._lock:
            out: list[dict[str, Any]] = []
            for sid, sh in list(self.shares.items()):
                if sh.committed and sh.path.exists():
                    if not sh.is_dir or sh.archive_ready:
                        sh.size = sh.path.stat().st_size
                    out.append(sh.to_dict())
                elif sh.committed and not sh.path.exists():
                    self.shares.pop(sid, None)
            return out

    def get_transfer(self, transfer_id: str) -> TransferEntity | None:
        with self._lock:
            return self.transfers.get(transfer_id)

    def get_share(self, share_id: str) -> ShareEntity | None:
        with self._lock:
            sh = self.shares.get(share_id)
            if sh and sh.committed and sh.path.exists():
                return sh
            return None

    def get_upload_lock(self, transfer_id: str) -> threading.Lock:
        with self._lock:
            if len(self.upload_locks) > 512:
                stale_ids = [
                    tid
                    for tid in list(self.upload_locks.keys())
                    if tid not in self.transfers or self.transfers[tid].state in TERMINAL_TRANSFER_STATES
                ]
                for tid in stale_ids:
                    self.upload_locks.pop(tid, None)
            lock = self.upload_locks.get(transfer_id)
            if lock is None:
                lock = threading.Lock()
                self.upload_locks[transfer_id] = lock
            return lock
