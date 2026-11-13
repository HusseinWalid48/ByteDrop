"""Speed, ETA, activity summary, and formatting helpers (3.2 & Section 2) shared across server-side transfers."""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Any


def format_bytes(size: int | float | None) -> str:
    """Formats byte count with rounding boundary unit promotion (e.g., 1073741823 -> '1.0 GB')."""
    if size is None or isinstance(size, bool) or not isinstance(size, (int, float)):
        return "0 B"
    if not math.isfinite(size) or size <= 0:
        return "0 B"
    k = 1024.0
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    if size < k:
        rounded_b = round(size)
        if rounded_b >= 1024:
            return f"1.0 {units[1]}"
        return f"{int(rounded_b)} B"
    idx = min(len(units) - 1, math.floor(math.log(size) / math.log(k)))
    val = size / (k ** idx)
    if round(val, 1) >= k and idx < len(units) - 1:
        idx += 1
        val = size / (k ** idx)
    return f"{val:.1f} {units[idx]}"


def format_speed(bytes_per_sec: int | float | None) -> str:
    """Formats speed: '850 KB/s' below 1 MB/s, otherwise '12.4 MB/s'."""
    if bytes_per_sec is None or isinstance(bytes_per_sec, bool) or not isinstance(bytes_per_sec, (int, float)):
        return "0 KB/s"
    if not math.isfinite(bytes_per_sec) or bytes_per_sec <= 0:
        return "0 KB/s"
    mb = 1024.0 * 1024.0
    if bytes_per_sec < mb:
        kb = max(1, round(bytes_per_sec / 1024.0))
        if kb >= 1024:
            return "1.0 MB/s"
        return f"{kb} KB/s"
    return f"{(bytes_per_sec / mb):.1f} MB/s"


def format_duration(seconds: int | float | None) -> str:
    """Formats duration: '45 s', '03:12', or '1:02:15'."""
    if seconds is None or isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return "0 s"
    if not math.isfinite(seconds) or seconds < 0:
        return "0 s"
    total_sec = round(seconds)
    if total_sec < 60:
        return f"{total_sec} s"
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class SpeedEstimator:
    """Server-side speed & ETA estimator (Section 3.2).

    - Samples bytes at most every 250 ms.
    - Exponentially smoothed speed over a ~3 s sliding window (EWMA, alpha = 0.3).
    - avg_speed = newly_transferred_bytes / elapsed_active_time.
    - eta = remaining_bytes / smoothed_speed, shown only after 1.5 s active time AND 64 KB newly transferred.
    - Clamps ETA change to ~20% per update to avoid jumping.
    - Marks Stalled if no bytes received for >= 5.0 s while active.
    - Resumed transfers: bytes already present count toward progress, NOT toward speed or 64 KB threshold.
    """

    SAMPLE_INTERVAL_SEC = 0.25
    WINDOW_SEC = 3.0
    ALPHA = 0.3
    MIN_ETA_ELAPSED_SEC = 1.5
    MIN_ETA_NEW_BYTES = 64 * 1024
    STALL_TIMEOUT_SEC = 5.0
    CONNECTION_LOST_TIMEOUT_SEC = 15.0
    UPLOAD_WAITING_PHONE_SEC = 45.0
    ETA_MAX_STEP_RATIO = 0.20

    def __init__(self, total_bytes: int, initial_offset: int = 0, now: float | None = None) -> None:
        t0 = now if now is not None else time.monotonic()
        self.total_bytes = max(0, int(total_bytes))
        self.initial_offset = max(0, int(initial_offset))
        self.bytes_done = self.initial_offset
        self.started_at = t0
        self.last_sample_time = t0
        self.last_progress_time = t0
        self.paused_at: float | None = None
        self.paused_duration: float = 0.0
        self.paused: bool = False

        self._samples: deque[tuple[float, int]] = deque()
        self._samples.append((t0, self.initial_offset))
        self.smoothed_speed: float = 0.0
        self.avg_speed: float = 0.0
        self.eta: float | None = None
        self.stalled: bool = False
        self.connection_lost: bool = False
        self.waiting_for_phone: bool = False

    def reset_resumed_offset(self, offset: int, now: float | None = None) -> None:
        t = now if now is not None else time.monotonic()
        self.initial_offset = max(0, int(offset))
        self.bytes_done = self.initial_offset
        self._samples.clear()
        self._samples.append((t, self.initial_offset))
        self.last_sample_time = t
        self.last_progress_time = t
        self.smoothed_speed = 0.0
        self.eta = None
        self.stalled = False
        self.connection_lost = False
        self.waiting_for_phone = False

    def pause(self, now: float | None = None) -> None:
        if self.paused:
            return
        t = now if now is not None else time.monotonic()
        self.paused = True
        self.paused_at = t
        self.stalled = False
        self.connection_lost = False
        self.waiting_for_phone = False

    def resume(self, now: float | None = None) -> None:
        if not self.paused:
            return
        t = now if now is not None else time.monotonic()
        if self.paused_at is not None:
            self.paused_duration += max(0.0, t - self.paused_at)
        self.paused = False
        self.paused_at = None
        self.last_sample_time = t
        self.last_progress_time = t
        self.stalled = False
        self.connection_lost = False
        self.waiting_for_phone = False
        self._samples.clear()
        self._samples.append((t, self.bytes_done))

    def active_elapsed(self, now: float | None = None) -> float:
        t = now if now is not None else time.monotonic()
        extra_pause = (t - self.paused_at) if (self.paused and self.paused_at is not None) else 0.0
        return max(0.001, (t - self.started_at) - self.paused_duration - extra_pause)

    def update(self, current_bytes_done: int, force: bool = False, now: float | None = None) -> dict[str, float | bool | None]:
        t = now if now is not None else time.monotonic()
        clamped_done = max(self.initial_offset, int(current_bytes_done))
        if clamped_done > self.bytes_done:
            if self.connection_lost or self.waiting_for_phone:
                self.initial_offset = self.bytes_done
                self._samples.clear()
                self._samples.append((self.last_progress_time, self.bytes_done))
            self.bytes_done = clamped_done
            self.last_progress_time = t
            self.stalled = False
            self.connection_lost = False
            self.waiting_for_phone = False

        if self.paused:
            return self.snapshot(now=t)

        idle_sec = t - self.last_progress_time
        if self.bytes_done > 0 and self.bytes_done < self.total_bytes:
            if idle_sec >= self.UPLOAD_WAITING_PHONE_SEC:
                self.waiting_for_phone = True
                self.connection_lost = True
                self.stalled = False
                self.smoothed_speed = 0.0
                self.eta = None
                return self.snapshot(now=t)
            if idle_sec >= self.CONNECTION_LOST_TIMEOUT_SEC:
                self.connection_lost = True
                self.stalled = False
                self.smoothed_speed = 0.0
                self.eta = None
                return self.snapshot(now=t)
            if idle_sec >= self.STALL_TIMEOUT_SEC:
                self.stalled = True
                self.smoothed_speed = 0.0
                self.eta = None
                return self.snapshot(now=t)

        dt_since_sample = t - self.last_sample_time
        if not force and dt_since_sample < self.SAMPLE_INTERVAL_SEC:
            return self.snapshot(now=t)

        self.last_sample_time = t
        self._samples.append((t, self.bytes_done))

        # Prune samples older than WINDOW_SEC (keeping at least 2 points)
        cutoff = t - self.WINDOW_SEC
        while len(self._samples) > 2 and self._samples[0][0] < cutoff:
            self._samples.popleft()

        oldest_t, oldest_b = self._samples[0]
        window_dt = max(0.001, t - oldest_t)
        window_db = max(0, self.bytes_done - oldest_b)
        instant_window_speed = window_db / window_dt

        if self.smoothed_speed <= 0.0:
            self.smoothed_speed = instant_window_speed
        else:
            self.smoothed_speed = (self.ALPHA * instant_window_speed) + ((1.0 - self.ALPHA) * self.smoothed_speed)

        elapsed = self.active_elapsed(now=t)
        newly_sent = max(0, self.bytes_done - self.initial_offset)
        self.avg_speed = newly_sent / elapsed

        remaining = max(0, self.total_bytes - self.bytes_done)
        if remaining == 0:
            self.eta = 0.0
        elif (
            elapsed >= self.MIN_ETA_ELAPSED_SEC
            and newly_sent >= self.MIN_ETA_NEW_BYTES
            and self.smoothed_speed > 1.0
            and not self.stalled
            and not self.connection_lost
        ):
            raw_eta = remaining / self.smoothed_speed
            if self.eta is not None and self.eta > 0 and abs(raw_eta - self.eta) / self.eta > self.ETA_MAX_STEP_RATIO:
                # Limit ETA change to ~20% per update unless approaching 0
                if raw_eta > self.eta:
                    self.eta = self.eta * (1.0 + self.ETA_MAX_STEP_RATIO)
                else:
                    self.eta = max(raw_eta, self.eta * (1.0 - self.ETA_MAX_STEP_RATIO))
            else:
                self.eta = raw_eta
        else:
            self.eta = None

        return self.snapshot(now=t)

    def snapshot(self, now: float | None = None) -> dict[str, float | bool | None]:
        t = now if now is not None else time.monotonic()
        elapsed = self.active_elapsed(now=t)
        newly_sent = max(0, self.bytes_done - self.initial_offset)
        self.avg_speed = newly_sent / elapsed
        inactive = self.paused or self.stalled or self.connection_lost or self.waiting_for_phone
        return {
            "speed": 0.0 if inactive else self.smoothed_speed,
            "avg_speed": self.avg_speed,
            "eta": None if inactive else self.eta,
            "elapsed": elapsed,
            "stalled": self.stalled,
            "connection_lost": self.connection_lost,
            "waiting_for_phone": self.waiting_for_phone,
            "paused": self.paused,
        }


def summarize_activity(
    transfers: list[dict[str, Any]],
    now_sec: float | None = None,
    prev_eta: float | None = None,
    connection_lost_sec: float = 15.0,
    upload_waiting_phone_sec: float = 45.0,
) -> dict[str, Any]:
    """Pure server-side activity summary matching ui/shared/format.js summarizeActivity (G2, G4 & H2)."""
    now = now_sec if now_sec is not None else time.time()
    active_moving: list[dict[str, Any]] = []
    stalled_list: list[dict[str, Any]] = []
    paused_list: list[dict[str, Any]] = []
    preparing_list: list[dict[str, Any]] = []
    waiting_list: list[dict[str, Any]] = []

    for item in transfers:
        st = str(item.get("state") or "").lower()
        if st in ("done", "completed", "cancelled", "rejected", "expired", "failed"):
            continue
        if st in ("preparing", "scanning", "zipping") or item.get("preparing"):
            preparing_list.append(item)
            continue
        if (
            st in ("paused", "interrupted", "connection_lost")
            or item.get("paused")
            or item.get("connection_lost")
            or item.get("offline_will_resume")
        ):
            paused_list.append(item)
            continue
        if st in ("accepted", "pending", "queued", "waiting"):
            waiting_list.append(item)
            continue
        if st in ("active", "uploading", "downloading"):
            f_obj = item.get("file") or {}
            size_v = int(item.get("size") or f_obj.get("size") or 0)
            done_v = int(item.get("bytes_done") or item.get("offset") or 0)
            spd_v = float(item.get("speed") or item.get("speed_bps") or 0.0)

            # G2: A transfer with 0 bytes transferred and 0 speed is waiting, never stalled or 0.0 KB/s active
            if done_v <= 0 and spd_v <= 0.0:
                waiting_list.append(item)
                continue

            last_p = item.get("last_progress_time") or item.get("last_byte_time") or item.get("updated_at")
            idle_sec = (now - float(last_p)) if isinstance(last_p, (int, float)) else None
            direction = str(item.get("direction") or "")
            is_download = direction == "pc_to_phone" or st == "downloading" or bool(item.get("isDownload"))
            incomplete = size_v == 0 or done_v < size_v

            # H2: Downloads idle >= connection_lost_sec (15s) or Uploads idle >= upload_waiting_phone_sec (45s)
            # are treated like paused on the indicator, NOT stalled and NOT active speed.
            if is_download and done_v > 0 and incomplete and idle_sec is not None and idle_sec >= connection_lost_sec:
                paused_list.append(item)
                continue
            if (
                not is_download
                and done_v > 0
                and incomplete
                and (
                    bool(item.get("waiting_for_phone"))
                    or (idle_sec is not None and idle_sec >= upload_waiting_phone_sec)
                )
            ):
                paused_list.append(item)
                continue

            is_stalled = bool(item.get("stalled")) and done_v > 0
            if (
                not is_stalled
                and done_v > 0
                and incomplete
                and idle_sec is not None
                and idle_sec >= 5.0
            ):
                is_stalled = True
            if is_stalled:
                stalled_list.append(item)
            else:
                active_moving.append(item)

    if active_moving:
        speed_bps = sum(max(0.0, float(t.get("speed") or t.get("speed_bps") or 0.0)) for t in active_moving)
        active_req_ids = {t.get("request_id") for t in active_moving if t.get("request_id")}

        remaining_bytes = 0
        max_elapsed = 0.0
        total_new_bytes = 0
        for t in active_moving:
            f_obj = t.get("file") or {}
            sz = max(0, int(t.get("size") or f_obj.get("size") or 0))
            done = max(0, int(t.get("bytes_done") or t.get("offset") or 0))
            resumed = max(0, int(t.get("resumed_offset") or 0))
            remaining_bytes += max(0, sz - done)
            total_new_bytes += max(0, done - resumed)
            el = float(t.get("elapsed") or t.get("elapsed_sec") or 0.0)
            if el == 0.0 and isinstance(t.get("started_at"), (int, float)):
                el = max(0.0, now - float(t["started_at"]))
            if el > max_elapsed:
                max_elapsed = el

        for q in waiting_list:
            req_id = q.get("request_id")
            if not active_req_ids or (req_id and req_id in active_req_ids):
                f_obj = q.get("file") or {}
                sz = max(0, int(q.get("size") or f_obj.get("size") or 0))
                done = max(0, int(q.get("bytes_done") or q.get("offset") or 0))
                remaining_bytes += max(0, sz - done)

        eta_seconds: float | None = None
        if remaining_bytes == 0:
            eta_seconds = 0.0
        elif max_elapsed >= 1.5 and total_new_bytes >= 64 * 1024 and speed_bps > 1.0:
            raw_eta = remaining_bytes / speed_bps
            if prev_eta is not None and prev_eta > 0 and abs(raw_eta - prev_eta) / prev_eta > 0.20:
                eta_seconds = prev_eta * 1.20 if raw_eta > prev_eta else max(raw_eta, prev_eta * 0.80)
            else:
                eta_seconds = raw_eta

        return {
            "state": "active",
            "speed_bps": round(speed_bps, 1),
            "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
            "active_count": len(active_moving),
            "waiting_count": len(waiting_list),
        }

    if preparing_list:
        return {
            "state": "preparing",
            "speed_bps": 0.0,
            "eta_seconds": None,
            "active_count": len(preparing_list),
            "waiting_count": len(waiting_list),
        }

    if stalled_list:
        return {
            "state": "stalled",
            "speed_bps": 0.0,
            "eta_seconds": None,
            "active_count": len(stalled_list),
            "waiting_count": len(waiting_list),
        }

    if paused_list:
        return {
            "state": "paused",
            "speed_bps": 0.0,
            "eta_seconds": None,
            "active_count": len(paused_list),
            "waiting_count": len(waiting_list),
        }

    if waiting_list:
        return {
            "state": "waiting",
            "speed_bps": 0.0,
            "eta_seconds": None,
            "active_count": 0,
            "waiting_count": len(waiting_list),
        }

    return {
        "state": "idle",
        "speed_bps": 0.0,
        "eta_seconds": None,
        "active_count": 0,
        "waiting_count": 0,
    }
