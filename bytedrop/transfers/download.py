"""Plain HTTP Range download handler (PC -> Phone) with 1 MiB chunks, interrupted/Range resume, and aggregate interval tracking."""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import threading
import time
import urllib.parse
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from bytedrop.auth import ByteDropHttpError
from bytedrop.paths import win_long_path
from bytedrop.state import TERMINAL_TRANSFER_STATES, TransferEntity, is_valid_id
from bytedrop.transfers.manager import TransferManager
from bytedrop.transfers.speed import SpeedEstimator

logger = logging.getLogger("bytedrop.transfers.download")

STREAM_CHUNK_SIZE = 1024 * 1024  # 1 MiB disk read chunks (G4)
EVENT_INTERVAL_SEC = 0.25        # 4 Hz progress/speed/ETA broadcasts
DISC_CHECK_INTERVAL_SEC = 0.25   # Check request.is_disconnected() at most every 8 chunks or 250 ms
DISC_CHECK_CHUNKS = 8


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """Parses HTTP Range header ('bytes=start-end' or 'bytes=-suffix') against file_size."""
    if not range_header or not range_header.startswith("bytes="):
        raise ValueError("Invalid Range header")
    spec = range_header.replace("bytes=", "", 1).split(",")[0].strip()
    start_str, end_str = spec.split("-", 1)
    if start_str == "":
        suffix_len = int(end_str)
        if suffix_len <= 0:
            raise ValueError("Invalid suffix length")
        start = max(0, file_size - suffix_len)
        end = file_size - 1
    else:
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
    if start < 0 or end >= file_size or start > end:
        raise ValueError("Range Not Satisfiable")
    return start, end


class _TransferStreamTracker:
    """Lock-protected byte coverage and active-stream counter across concurrent Range streams."""

    def __init__(self, file_size: int) -> None:
        self.lock = threading.Lock()
        self.file_size = max(0, int(file_size))
        self.intervals: list[tuple[int, int]] = []
        self.active_streams: int = 0
        self.history_recorded: bool = False

    def reset(self, file_size: int) -> None:
        with self.lock:
            self.file_size = max(0, int(file_size))
            self.intervals.clear()
            self.active_streams = 0
            self.history_recorded = False

    def add_interval(self, start: int, end_exclusive: int) -> int:
        with self.lock:
            s = max(0, min(self.file_size, int(start)))
            e = max(0, min(self.file_size, int(end_exclusive)))
            if e > s:
                merged: list[tuple[int, int]] = []
                placed = False
                for cur_s, cur_e in self.intervals:
                    if cur_e < s:
                        merged.append((cur_s, cur_e))
                    elif cur_s > e:
                        if not placed:
                            merged.append((s, e))
                            placed = True
                        merged.append((cur_s, cur_e))
                    else:
                        s = min(s, cur_s)
                        e = max(e, cur_e)
                if not placed:
                    merged.append((s, e))
                self.intervals = merged
            return sum(ie - is_ for is_, ie in self.intervals)

    def covered_bytes(self) -> int:
        with self.lock:
            return sum(ie - is_ for is_, ie in self.intervals)


def _build_content_disposition(filename: str, inline: bool = False) -> str:
    """Builds a header-safe Content-Disposition value with sanitized ASCII fallback and RFC 5987 UTF-8."""
    disposition_type = "inline" if inline else "attachment"
    safe_ascii = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in ('"', "\\", "/", ";", "\r", "\n") else "_"
        for ch in filename
    ).strip() or "download"
    while "__" in safe_ascii:
        safe_ascii = safe_ascii.replace("__", "_")
    encoded_filename = urllib.parse.quote(filename.replace("\r", "").replace("\n", ""), safe="")
    return f"{disposition_type}; filename=\"{safe_ascii}\"; filename*=UTF-8''{encoded_filename}"


class DownloadHandler:
    """Streams shared PC files with HTTP 206/416 Range support, G4 interrupted state, and 4 Hz speed/ETA."""

    def __init__(self, manager: TransferManager) -> None:
        self.manager = manager
        self._trackers_lock = threading.Lock()
        self._trackers: dict[str, _TransferStreamTracker] = {}

    def _get_tracker(self, transfer_id: str, file_size: int) -> _TransferStreamTracker:
        with self._trackers_lock:
            tracker = self._trackers.get(transfer_id)
            if tracker is None:
                tracker = _TransferStreamTracker(file_size)
                self._trackers[transfer_id] = tracker
            else:
                with tracker.lock:
                    tracker.file_size = max(0, int(file_size))
            return tracker

    def _find_transfer_for_share(self, share_id: str) -> TransferEntity | None:
        with self.manager._lock:
            all_matching = [tr for tr in self.manager.transfers.values() if tr.share_id == share_id]
            for tr in reversed(all_matching):
                if tr.state not in TERMINAL_TRANSFER_STATES:
                    return tr
            if all_matching:
                return all_matching[-1]
        return None

    async def serve_share(
        self,
        share_id: str,
        request: Request,
        device_id: str = "phone",
        inline: bool = False,
        via: str | None = None,
    ) -> Response:
        if not is_valid_id(share_id):
            raise ByteDropHttpError(400, "Invalid share id", "BAD_SHARE_ID")

        tr = self._find_transfer_for_share(share_id)
        if tr is not None and not inline:
            if tr.state in ("cancelled", "rejected", "expired"):
                return JSONResponse(
                    status_code=410,
                    content={"detail": "Transfer was cancelled", "code": "TRANSFER_CANCELLED"},
                )
            if tr.state == "paused":
                return JSONResponse(
                    status_code=423,
                    content={"detail": "Transfer is paused", "code": "TRANSFER_PAUSED"},
                )

        share = self.manager.get_share(share_id)
        if share is None:
            raise ByteDropHttpError(404, "Shared file not found", "SHARE_NOT_FOUND")

        file_path: Path = share.path
        file_size = file_path.stat().st_size
        guessed_mime, _ = mimetypes.guess_type(share.name)
        content_type = guessed_mime or "application/octet-stream"
        content_disposition = _build_content_disposition(share.name, inline=inline)

        range_header = request.headers.get("range")
        is_partial = False
        start = 0
        end = max(0, file_size - 1)

        if range_header and file_size > 0:
            try:
                start, end = parse_range_header(range_header, file_size)
                is_partial = True
            except ValueError:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}"},
                )

        content_length = (end - start + 1) if file_size > 0 else 0
        now_mono = time.monotonic()
        tracker = self._get_tracker(tr.id if tr is not None else share_id, file_size)

        if tr is not None and not inline:
            with self.manager._lock:
                tr.device_id = device_id
                tr.file.size = file_size
                if via in ("Cloud", "Wi-Fi"):
                    tr.via = via
                if start > 0 and tracker.covered_bytes() < start:
                    tracker.add_interval(0, start)
                covered_so_far = tracker.covered_bytes()

                if tr.state == "done":
                    if start == 0 and tracker.active_streams == 0:
                        tracker.reset(file_size)
                        covered_so_far = 0
                    tr.state = "active"
                    tr.bytes_done = covered_so_far
                    tr.resumed_offset = covered_so_far
                    tr.started_at = time.time()
                    tr.completed_at = None
                    tr.interrupted_at = None
                    tr.speed = 0.0
                    tr.avg_speed = 0.0
                    tr.eta = None
                    tr.elapsed = 0.0
                    tr.stalled = False
                    est = SpeedEstimator(total_bytes=file_size, initial_offset=covered_so_far, now=now_mono)
                    self.manager.estimators[tr.id] = est
                elif tr.state in ("pending", "accepted", "interrupted"):
                    was_interrupted = tr.state == "interrupted"
                    if tr.started_at is None:
                        tr.started_at = time.time()
                    tr.transition_to("active")
                    tr.bytes_done = max(tr.bytes_done, covered_so_far)
                    tr.resumed_offset = tr.bytes_done
                    tr.stalled = False
                    existing_est = self.manager.estimators.get(tr.id)
                    if was_interrupted and existing_est is not None:
                        existing_est.reset_resumed_offset(tr.bytes_done, now=now_mono)
                        est = existing_est
                    else:
                        est = SpeedEstimator(total_bytes=file_size, initial_offset=tr.bytes_done, now=now_mono)
                        self.manager.estimators[tr.id] = est
                else:
                    existing_active_est = self.manager.estimators.get(tr.id)
                    if existing_active_est is not None:
                        est = existing_active_est
                    else:
                        est = SpeedEstimator(total_bytes=file_size, initial_offset=covered_so_far, now=now_mono)
                        self.manager.estimators[tr.id] = est
                dto_initial = tr.to_dict()

            self.manager.events.emit({"type": "transfer_updated", "transfer": dto_initial})
            self.manager.emit_activity_summary(force=True)
        else:
            est = SpeedEstimator(total_bytes=file_size, initial_offset=start, now=now_mono)

        async def stream_file_bytes() -> AsyncIterator[bytes]:
            with tracker.lock:
                tracker.active_streams += 1

            served_offset = start
            remaining = content_length
            last_emit = time.monotonic()
            last_disc_check = last_emit
            chunks_since_check = 0
            aborted = False
            disconnected = False
            pause_hold_expired = False

            fh = await asyncio.to_thread(open, win_long_path(file_path), "rb")
            try:
                if start > 0:
                    await asyncio.to_thread(fh.seek, start)

                while remaining > 0:
                    if tr is not None and not inline and tr.state in TERMINAL_TRANSFER_STATES:
                        aborted = True
                        break

                    t_check = time.monotonic()
                    if chunks_since_check >= DISC_CHECK_CHUNKS or (t_check - last_disc_check) >= DISC_CHECK_INTERVAL_SEC:
                        chunks_since_check = 0
                        last_disc_check = t_check
                        if await request.is_disconnected():
                            disconnected = True
                            aborted = True
                            break

                    if tr is not None and not inline and tr.state == "paused":
                        pause_started = time.monotonic()
                        hold_limit = float(self.manager.config.pause_hold_seconds)
                        while tr.state == "paused":
                            if await request.is_disconnected():
                                disconnected = True
                                aborted = True
                                break
                            if (time.monotonic() - pause_started) >= hold_limit:
                                pause_hold_expired = True
                                aborted = True
                                break
                            await asyncio.sleep(0.05)
                        if aborted or tr.state in TERMINAL_TRANSFER_STATES:
                            aborted = True
                            break

                    read_len = min(STREAM_CHUNK_SIZE, remaining)
                    chunk = await asyncio.to_thread(fh.read, read_len)
                    if not chunk:
                        aborted = True
                        break

                    if tr is not None and not inline and tr.state in TERMINAL_TRANSFER_STATES:
                        aborted = True
                        break

                    chunk_start = served_offset
                    chunk_end = served_offset + len(chunk)
                    remaining -= len(chunk)
                    served_offset = chunk_end
                    chunks_since_check += 1

                    covered_now = tracker.add_interval(chunk_start, chunk_end)
                    if tr is not None and not inline and tr.state not in TERMINAL_TRANSFER_STATES:
                        with self.manager._lock:
                            tr.bytes_done = max(tr.bytes_done, covered_now)
                            tr.updated_at = time.time()

                    yield chunk

                    if tr is not None and not inline and tr.state in TERMINAL_TRANSFER_STATES:
                        aborted = True
                        break

                    t_now = time.monotonic()
                    if not inline and (t_now - last_emit) >= EVENT_INTERVAL_SEC:
                        last_emit = t_now
                        if tr is not None and tr.state == "paused":
                            continue
                        with self.manager._lock:
                            covered_metric = tracker.covered_bytes()
                            metrics = est.update(covered_metric, force=True, now=t_now)
                            if tr is not None and tr.state not in TERMINAL_TRANSFER_STATES:
                                tr.bytes_done = max(tr.bytes_done, covered_metric)
                                tr.updated_at = time.time()
                                tr.speed = float(metrics["speed"] or 0.0)
                                tr.avg_speed = float(metrics["avg_speed"] or 0.0)
                                tr.eta = float(metrics["eta"]) if metrics["eta"] is not None else None
                                tr.elapsed = float(metrics["elapsed"] or 0.0)
                                tr.stalled = bool(metrics["stalled"])
                                dto_tick = tr.to_dict()
                            else:
                                dto_tick = None
                        if dto_tick is not None:
                            self.manager.events.emit({"type": "transfer_updated", "transfer": dto_tick})
                            self.manager.emit_activity_summary()
            except (GeneratorExit, asyncio.CancelledError):
                disconnected = True
                aborted = True
                raise
            except Exception as exc:
                logger.warning("Download stream error for %s: %s", share.name, exc)
                disconnected = True
                aborted = True
            finally:
                try:
                    fh.close()
                except OSError as close_exc:
                    logger.debug("Error closing file handle for %s: %s", share.name, close_exc)

                with tracker.lock:
                    tracker.active_streams = max(0, tracker.active_streams - 1)
                    still_active = tracker.active_streams
                    covered_total = sum(ie - is_ for is_, ie in tracker.intervals)
                    all_covered = (
                        (file_size == 0 and remaining == 0 and not aborted)
                        or (file_size > 0 and covered_total >= file_size)
                    )
                    should_complete = (
                        not inline
                        and all_covered
                        and still_active == 0
                        and not tracker.history_recorded
                        and (tr is None or tr.state not in TERMINAL_TRANSFER_STATES)
                    )
                    if should_complete:
                        tracker.history_recorded = True

                if should_complete:
                    t_end = time.monotonic()
                    metrics = est.update(file_size, force=True, now=t_end)
                    elapsed_sec = float(metrics["elapsed"] or 0.001)
                    avg_spd = float(metrics["avg_speed"] or 0.0)
                    dto_done: dict[str, object] | None = None
                    if tr is not None:
                        with self.manager._lock:
                            tr.bytes_done = file_size
                            tr.updated_at = time.time()
                            tr.speed = float(metrics["speed"] or 0.0)
                            tr.avg_speed = avg_spd
                            tr.eta = 0.0
                            tr.elapsed = elapsed_sec
                            tr.stalled = False
                            tr.transition_to("done")
                            self.manager.estimators.pop(tr.id, None)
                            dto_done = tr.to_dict()
                        if dto_done is not None:
                            self.manager.events.emit({"type": "transfer_updated", "transfer": dto_done})
                        self.manager.emit_activity_summary(force=True)

                    hist_entry = self.manager.history.record(
                        share.name,
                        share.category,
                        file_size,
                        "OUTGOING",
                        elapsed_sec,
                        avg_spd,
                        expected_size=file_size,
                        state="done",
                        is_folder=share.is_dir,
                    )
                    if hist_entry is not None:
                        self.manager.events.emit({"type": "history_updated", "entry": hist_entry})
                elif not inline and tr is not None and still_active == 0:
                    dto_end: dict[str, object] | None = None
                    with self.manager._lock:
                        if tr.state not in TERMINAL_TRANSFER_STATES:
                            if pause_hold_expired or tr.state == "paused":
                                tr.speed = 0.0
                                tr.eta = None
                                tr.stalled = False
                                dto_end = tr.to_dict()
                            elif (disconnected or aborted or remaining > 0) and covered_total < file_size:
                                tr.transition_to("interrupted")
                                tr.bytes_done = max(tr.bytes_done, covered_total)
                                tr.speed = 0.0
                                tr.eta = None
                                tr.stalled = False
                                dto_end = tr.to_dict()
                    if dto_end is not None:
                        self.manager.events.emit({"type": "transfer_updated", "transfer": dto_end})
                    self.manager.emit_activity_summary(force=True)

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Content-Disposition": content_disposition,
        }
        if is_partial:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

        return StreamingResponse(
            stream_file_bytes(),
            status_code=206 if is_partial else 200,
            media_type=content_type,
            headers=headers,
        )
