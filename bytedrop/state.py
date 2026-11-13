"""Core domain models and state machines for Transfers, Devices, and Shares."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")

TERMINAL_TRANSFER_STATES = frozenset({"done", "failed", "cancelled", "rejected", "expired"})
ACTIVE_TRANSFER_STATES = frozenset({"pending", "accepted", "active", "paused", "interrupted"})

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"accepted", "rejected", "cancelled", "expired", "failed"},
    "accepted": {"active", "paused", "interrupted", "done", "cancelled", "expired", "failed"},
    "active": {"paused", "interrupted", "done", "cancelled", "expired", "failed"},
    "paused": {"active", "interrupted", "done", "cancelled", "expired", "failed"},
    "interrupted": {"active", "paused", "done", "cancelled", "expired", "failed"},
    "done": set(),
    "failed": set(),
    "cancelled": set(),
    "rejected": set(),
    "expired": set(),
}


def is_valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(VALID_ID_RE.match(value))


@dataclass
class TransferFile:
    name: str
    size: int
    category: str
    thumbnail: str | None = None
    is_folder: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": int(self.size),
            "category": self.category,
            "thumbnail": self.thumbnail,
            "is_folder": self.is_folder,
        }


@dataclass
class TransferEntity:
    id: str
    request_id: str
    batch_index: int
    batch_size: int
    direction: str  # "phone_to_pc" | "pc_to_phone"
    device_id: str
    device_name: str
    file: TransferFile
    state: str = "pending"
    bytes_done: int = 0
    resumed_offset: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    interrupted_at: float | None = None
    speed: float = 0.0
    avg_speed: float = 0.0
    eta: float | None = None
    elapsed: float = 0.0
    stalled: bool = False
    waiting_for_phone: bool = False
    error: str | None = None
    saved_as: str | None = None
    share_id: str | None = None
    via: str = "Wi-Fi"

    def can_transition_to(self, target_state: str) -> bool:
        if self.state == target_state:
            return True
        return target_state in ALLOWED_TRANSITIONS.get(self.state, set())

    def transition_to(self, target_state: str, error: str | None = None) -> bool:
        if not self.can_transition_to(target_state):
            return False
        now = time.time()
        self.state = target_state
        self.updated_at = now
        if target_state == "active":
            if self.started_at is None:
                self.started_at = now
            self.interrupted_at = None
            self.waiting_for_phone = False
        elif target_state == "interrupted":
            if self.interrupted_at is None:
                self.interrupted_at = now
            self.stalled = False
        if target_state in TERMINAL_TRANSFER_STATES:
            self.completed_at = now
            self.interrupted_at = None
            self.stalled = False
            self.waiting_for_phone = False
            if self.started_at is not None:
                self.elapsed = max(0.001, now - self.started_at)
        if error is not None:
            self.error = error
        return True

    @property
    def progress_pct(self) -> int:
        if self.state == "done":
            return 100
        if self.file.size <= 0:
            return 100 if self.state == "done" else 0
        return min(99, max(0, int((self.bytes_done / self.file.size) * 100)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "batch_index": self.batch_index,
            "batch_size": self.batch_size,
            "direction": self.direction,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "file": self.file.to_dict(),
            "state": self.state,
            "bytes_done": int(self.bytes_done),
            "resumed_offset": int(self.resumed_offset),
            "progress": self.progress_pct,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "interrupted_at": self.interrupted_at,
            "speed": round(self.speed, 1),
            "avg_speed": round(self.avg_speed, 1),
            "eta": round(self.eta, 1) if self.eta is not None else None,
            "elapsed": round(self.elapsed, 1),
            "stalled": self.stalled,
            "waiting_for_phone": self.waiting_for_phone,
            "error": self.error,
            "saved_as": self.saved_as or self.file.name,
            "share_id": self.share_id,
            "via": self.via,
        }


@dataclass
class ShareEntity:
    id: str
    request_id: str
    file_index: int
    path: Path
    name: str
    size: int
    uncompressed_size: int
    category: str
    is_dir: bool = False
    archive_ready: bool = True
    skipped_count: int = 0
    skipped_reasons: list[str] = field(default_factory=list)
    thumbnail: str | None = None
    created_at: float = field(default_factory=time.time)
    committed: bool = False
    target_device_id: str | None = None
    auto_download_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        reported_size = 0 if (self.is_dir and not self.archive_ready) else int(self.size)
        return {
            "id": self.id,
            "request_id": self.request_id,
            "file_index": self.file_index,
            "name": self.name,
            "size": reported_size,
            "category": self.category,
            "is_dir": self.is_dir,
            "is_folder": self.is_dir,
            "archive_ready": self.archive_ready,
            "skipped_count": self.skipped_count,
            "skipped_reasons": list(self.skipped_reasons),
            "thumbnail": self.thumbnail,
            "created_at": self.created_at,
            "committed": self.committed,
            "target_device_id": self.target_device_id,
            "auto_download_allowed": self.auto_download_allowed,
        }


@dataclass
class DeviceEntity:
    id: str
    name: str
    ip: str
    via: str  # "LAN" | "Cloud"
    connected_at: str
    online: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "ip": self.ip,
            "via": self.via,
            "connected_at": self.connected_at,
            "online": self.online,
        }


@dataclass
class BlockedDeviceRecord:
    device_id: str
    name: str
    ip: str
    blocked_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.device_id,
            "device_id": self.device_id,
            "name": self.name,
            "ip": self.ip,
            "blocked_at": self.blocked_at,
        }
