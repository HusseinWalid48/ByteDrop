"""Configuration management with atomic save in %APPDATA%\\ByteDrop\\config.json."""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Any

from bytedrop.fsutil import CATEGORY_EXTENSIONS, hide_path
from bytedrop.paths import get_appdata_dir, get_default_upload_dir

logger = logging.getLogger("bytedrop.config")

ACCENT_PALETTES: dict[str, dict[str, str]] = {
    "blue": {"from": "#1d4ed8", "to": "#3b82f6", "light": "#60a5fa", "rgb": "59, 130, 246", "darkRgb": "29, 78, 216"},
    "purple": {"from": "#6d28d9", "to": "#8b5cf6", "light": "#a78bfa", "rgb": "139, 92, 246", "darkRgb": "109, 40, 217"},
    "green": {"from": "#047857", "to": "#10b981", "light": "#34d399", "rgb": "16, 185, 129", "darkRgb": "4, 120, 87"},
    "cyan": {"from": "#0e7490", "to": "#06b6d4", "light": "#22d3ee", "rgb": "6, 182, 212", "darkRgb": "14, 116, 144"},
    "rose": {"from": "#be123c", "to": "#f43f5e", "light": "#fb7185", "rgb": "244, 63, 94", "darkRgb": "190, 18, 60"},
}


class ConfigManager:
    """Thread-safe configuration store persisted in %APPDATA%\\ByteDrop\\config.json."""

    def __init__(self, appdata_dir: Path | None = None) -> None:
        self.appdata_dir = get_appdata_dir(appdata_dir)
        self.config_path = self.appdata_dir / "config.json"
        self.default_upload_dir = get_default_upload_dir()
        self._lock = threading.RLock()

        self.corrupt_config_recovered: bool = False
        raw = self._load_from_disk()
        self.theme: str = str(raw.get("theme", "dark"))
        if self.theme not in ("dark", "light"):
            self.theme = "dark"

        self.accent: str = str(raw.get("accent", "blue"))
        if self.accent not in ACCENT_PALETTES:
            self.accent = "blue"

        self.language: str = str(raw.get("language", "en"))
        if self.language not in ("en", "ar"):
            self.language = "en"

        self.saved_upload_dir_str: str = str(raw.get("upload_dir") or self.default_upload_dir)
        self.upload_dir: Path = self.default_upload_dir
        self.resolve_active_upload_dir(self.saved_upload_dir_str)

        self.preferred_ip: str = str(raw.get("preferred_ip", ""))
        self.cloud_auto_start: bool = bool(raw.get("cloud_auto_start", True))
        self.clipboard_sync_enabled: bool = bool(raw.get("clipboard_sync_enabled", False))
        self.auto_accept_local: bool = bool(raw.get("auto_accept_local", False))
        self.max_folder_gb: int = max(1, int(raw.get("max_folder_gb", 20)))
        self.max_folder_files: int = max(100, int(raw.get("max_folder_files", 10000)))
        self.max_request_files: int = max(1, int(raw.get("max_request_files", 2000)))
        self.shared_ttl_hours: int = max(1, int(raw.get("shared_ttl_hours", 24)))
        self.waiting_ttl_minutes: int = max(1, int(raw.get("waiting_ttl_minutes", 10)))
        self.interrupted_timeout_seconds: int = max(5, int(raw.get("interrupted_timeout_seconds", 600)))
        self.pause_hold_seconds: float = max(0.1, float(raw.get("pause_hold_seconds", 90)))
        self.connection_lost_seconds: float = max(1.0, float(raw.get("connection_lost_seconds", 15.0)))
        self.upload_waiting_phone_seconds: float = max(1.0, float(raw.get("upload_waiting_phone_seconds", 45.0)))
        self.notifications_enabled: bool = bool(raw.get("notifications_enabled", True))
        self.tray_mode_enabled: bool = bool(raw.get("tray_mode_enabled", False))
        self.start_minimized: bool = bool(raw.get("start_minimized", False))
        self.autostart_windows: bool = bool(raw.get("autostart_windows", False))

        self.save()

    def _defaults(self) -> dict[str, Any]:
        return {
            "theme": "dark",
            "accent": "blue",
            "language": "en",
            "upload_dir": str(self.default_upload_dir),
            "preferred_ip": "",
            "cloud_auto_start": True,
            "clipboard_sync_enabled": False,
            "auto_accept_local": False,
            "max_folder_gb": 20,
            "max_folder_files": 10000,
            "max_request_files": 2000,
            "shared_ttl_hours": 24,
            "waiting_ttl_minutes": 10,
            "interrupted_timeout_seconds": 600,
            "pause_hold_seconds": 90,
            "connection_lost_seconds": 15.0,
            "upload_waiting_phone_seconds": 45.0,
            "notifications_enabled": True,
            "tray_mode_enabled": False,
            "start_minimized": False,
            "autostart_windows": False,
        }

    def _load_from_disk(self) -> dict[str, Any]:
        defaults = self._defaults()
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("config.json root must be a JSON object")
                defaults.update(data)
            except Exception as exc:
                logger.warning("Corrupt config.json (%s); renaming to config.json.bad and resetting defaults", exc)
                self.corrupt_config_recovered = True
                bad_path = self.config_path.with_name("config.json.bad")
                try:
                    self.config_path.replace(bad_path)
                except OSError as move_exc:
                    logger.warning("Could not rename corrupt config.json to config.json.bad: %s", move_exc)
        return defaults

    def resolve_active_upload_dir(self, candidate_dir_str: str) -> bool:
        """Resolves upload_dir and creates category subfolders; falls back to default_upload_dir on failure."""
        try:
            target = Path(candidate_dir_str).resolve()
            if os.name == "nt" and target.drive and not Path(target.drive + "\\").exists():
                raise OSError(f"Drive {target.drive} is not mounted")
            target.mkdir(parents=True, exist_ok=True)
            for cat in (*CATEGORY_EXTENSIONS.keys(), "Others"):
                (target / cat).mkdir(parents=True, exist_ok=True)
            partial = target / ".partial"
            partial.mkdir(parents=True, exist_ok=True)
            hide_path(partial)
            self.upload_dir = target
            return True
        except Exception as exc:
            logger.warning("Upload dir '%s' unavailable (%s); falling back for session", candidate_dir_str, exc)
            self.upload_dir = self.default_upload_dir
            try:
                self.upload_dir.mkdir(parents=True, exist_ok=True)
                for cat in (*CATEGORY_EXTENSIONS.keys(), "Others"):
                    (self.upload_dir / cat).mkdir(parents=True, exist_ok=True)
                partial = self.upload_dir / ".partial"
                partial.mkdir(parents=True, exist_ok=True)
                hide_path(partial)
            except OSError as inner_exc:
                logger.error("Fallback upload dir creation error: %s", inner_exc)
            return False

    @property
    def partial_dir(self) -> Path:
        p = self.upload_dir / ".partial"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def set_upload_dir(self, new_dir: str) -> str:
        with self._lock:
            target = Path(new_dir).resolve()
            target.mkdir(parents=True, exist_ok=True)
            self.saved_upload_dir_str = str(target)
            self.resolve_active_upload_dir(self.saved_upload_dir_str)
            self.save()
            return str(self.upload_dir)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "theme": self.theme,
                "accent": self.accent,
                "language": self.language,
                "upload_dir": self.saved_upload_dir_str,
                "preferred_ip": self.preferred_ip,
                "cloud_auto_start": self.cloud_auto_start,
                "clipboard_sync_enabled": self.clipboard_sync_enabled,
                "auto_accept_local": self.auto_accept_local,
                "max_folder_gb": self.max_folder_gb,
                "max_folder_files": self.max_folder_files,
                "max_request_files": self.max_request_files,
                "shared_ttl_hours": self.shared_ttl_hours,
                "waiting_ttl_minutes": self.waiting_ttl_minutes,
                "interrupted_timeout_seconds": self.interrupted_timeout_seconds,
                "pause_hold_seconds": self.pause_hold_seconds,
                "connection_lost_seconds": self.connection_lost_seconds,
                "upload_waiting_phone_seconds": self.upload_waiting_phone_seconds,
                "notifications_enabled": self.notifications_enabled,
                "tray_mode_enabled": self.tray_mode_enabled,
                "start_minimized": self.start_minimized,
                "autostart_windows": self.autostart_windows,
            }

    def public_subset(self, include_desktop_fields: bool = False) -> dict[str, Any]:
        """Returns settings subset safe for UIs (never exposes desktop theme/accent/language or paths to phone web client)."""
        base: dict[str, Any] = {
            "max_request_files": self.max_request_files,
            "waiting_ttl_minutes": self.waiting_ttl_minutes,
            "interrupted_timeout_seconds": self.interrupted_timeout_seconds,
            "connection_lost_seconds": self.connection_lost_seconds,
            "upload_waiting_phone_seconds": self.upload_waiting_phone_seconds,
        }
        if include_desktop_fields:
            base.update({
                "theme": self.theme,
                "accent": self.accent,
                "language": self.language,
                "download_dir": str(self.upload_dir),
                "preferred_ip": self.preferred_ip,
                "cloud_auto_start": self.cloud_auto_start,
                "clipboard_sync_enabled": self.clipboard_sync_enabled,
                "auto_accept_local": self.auto_accept_local,
                "max_folder_gb": self.max_folder_gb,
                "max_folder_files": self.max_folder_files,
                "pause_hold_seconds": self.pause_hold_seconds,
                "notifications_enabled": self.notifications_enabled,
                "tray_mode_enabled": self.tray_mode_enabled,
                "start_minimized": self.start_minimized,
                "autostart_windows": self.autostart_windows,
                "corrupt_config_recovered": self.corrupt_config_recovered,
            })
        return base

    def update(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            if "theme" in kwargs and kwargs["theme"] in ("dark", "light"):
                self.theme = str(kwargs["theme"])
            if "accent" in kwargs and kwargs["accent"] in ACCENT_PALETTES:
                self.accent = str(kwargs["accent"])
            if "language" in kwargs and kwargs["language"] in ("en", "ar"):
                self.language = str(kwargs["language"])
            if "preferred_ip" in kwargs and kwargs["preferred_ip"] is not None:
                self.preferred_ip = str(kwargs["preferred_ip"]).strip()
            if "cloud_auto_start" in kwargs and kwargs["cloud_auto_start"] is not None:
                self.cloud_auto_start = bool(kwargs["cloud_auto_start"])
            if "clipboard_sync_enabled" in kwargs and kwargs["clipboard_sync_enabled"] is not None:
                self.clipboard_sync_enabled = bool(kwargs["clipboard_sync_enabled"])
            if "auto_accept_local" in kwargs and kwargs["auto_accept_local"] is not None:
                self.auto_accept_local = bool(kwargs["auto_accept_local"])
            if "max_folder_gb" in kwargs and kwargs["max_folder_gb"] is not None:
                self.max_folder_gb = max(1, min(200, int(kwargs["max_folder_gb"])))
            if "max_folder_files" in kwargs and kwargs["max_folder_files"] is not None:
                self.max_folder_files = max(10, int(kwargs["max_folder_files"]))
            if "max_request_files" in kwargs and kwargs["max_request_files"] is not None:
                self.max_request_files = max(1, int(kwargs["max_request_files"]))
            if "waiting_ttl_minutes" in kwargs and kwargs["waiting_ttl_minutes"] is not None:
                self.waiting_ttl_minutes = max(1, int(kwargs["waiting_ttl_minutes"]))
            if "interrupted_timeout_seconds" in kwargs and kwargs["interrupted_timeout_seconds"] is not None:
                self.interrupted_timeout_seconds = max(5, int(kwargs["interrupted_timeout_seconds"]))
            if "pause_hold_seconds" in kwargs and kwargs["pause_hold_seconds"] is not None:
                self.pause_hold_seconds = max(0.1, float(kwargs["pause_hold_seconds"]))
            if "connection_lost_seconds" in kwargs and kwargs["connection_lost_seconds"] is not None:
                self.connection_lost_seconds = max(1.0, float(kwargs["connection_lost_seconds"]))
            if "upload_waiting_phone_seconds" in kwargs and kwargs["upload_waiting_phone_seconds"] is not None:
                self.upload_waiting_phone_seconds = max(1.0, float(kwargs["upload_waiting_phone_seconds"]))
            if "notifications_enabled" in kwargs and kwargs["notifications_enabled"] is not None:
                self.notifications_enabled = bool(kwargs["notifications_enabled"])
            if "tray_mode_enabled" in kwargs and kwargs["tray_mode_enabled"] is not None:
                self.tray_mode_enabled = bool(kwargs["tray_mode_enabled"])
            if "start_minimized" in kwargs and kwargs["start_minimized"] is not None:
                self.start_minimized = bool(kwargs["start_minimized"])
            if "autostart_windows" in kwargs and kwargs["autostart_windows"] is not None:
                self.autostart_windows = bool(kwargs["autostart_windows"])
            return self.save()

    @property
    def corrupt_recovered(self) -> bool:
        return self.corrupt_config_recovered

    def save(self) -> dict[str, Any]:
        """Atomically writes settings to %APPDATA%\\ByteDrop\\config.json."""
        with self._lock:
            data = self.to_dict()
            try:
                self.appdata_dir.mkdir(parents=True, exist_ok=True)
                tmp_path = self.config_path.with_name(f"config.{secrets.token_hex(4)}.tmp")
                tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                tmp_path.replace(self.config_path)
            except OSError as exc:
                logger.error("Failed saving config.json: %s", exc)
            return data


AppConfig = ConfigManager

