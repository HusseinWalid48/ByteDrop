"""Passive Windows Mobile Hotspot (192.168.137.1) detector and Windows Hotspot settings launcher (G1)."""
from __future__ import annotations

import logging
import os
import socket
import threading
from typing import Any

import psutil  # type: ignore[import-untyped]

from bytedrop.auth import AuthManager
from bytedrop.events import EventBus
from bytedrop.net import generate_qr_data_uri

logger = logging.getLogger("bytedrop.desktop.hotspot")

HOTSPOT_SUBNET_PREFIX = "192.168.137."
HOTSPOT_DEFAULT_IP = "192.168.137.1"
WINDOWS_HOTSPOT_SETTINGS_URI = "ms-settings:network-mobilehotspot"


def detect_hotspot_ip() -> str | None:
    """Passively checks network interfaces via psutil for the standard Windows Mobile Hotspot IP (192.168.137.1)."""
    try:
        found_subnet_ip: str | None = None
        for addrs in psutil.net_if_addrs().values():
            for snic in addrs:
                if snic.family == socket.AF_INET:
                    ip = str(snic.address or "").strip()
                    if ip == HOTSPOT_DEFAULT_IP:
                        return ip
                    if ip.startswith(HOTSPOT_SUBNET_PREFIX) and found_subnet_ip is None:
                        found_subnet_ip = ip
        return found_subnet_ip
    except Exception as exc:
        logger.debug("Passive hotspot IP scan error: %s", exc)
        return None


class HotspotManager:
    """Passively detects Windows 10/11 Mobile Hotspot (192.168.137.1) and opens Windows Hotspot settings."""

    def __init__(self, auth: AuthManager, events: EventBus, port: int) -> None:
        self.auth = auth
        self.events = events
        self.port = port
        self._lock = threading.RLock()
        self.detected: bool = False
        self.active: bool = False
        self.ip: str | None = None
        self.url: str | None = None
        self.link_qr: str = ""
        self.check_and_update(emit=False)

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "detected": self.detected,
                "active": self.active,
                "ip": self.ip,
                "hotspot_ip": self.ip,
                "url": self.url,
                "hotspot_url": self.url,
                "link_qr": self.link_qr,
                "hotspot_qr": self.link_qr,
            }

    def check_and_update(self, emit: bool = True) -> dict[str, Any]:
        """Passively checks whether 192.168.137.1 is present and updates the Hotspot QR."""
        hs_ip = detect_hotspot_ip()
        changed = False
        with self._lock:
            is_detected = hs_ip is not None
            if is_detected != self.detected or hs_ip != self.ip:
                changed = True
                self.detected = is_detected
                self.active = is_detected
                self.ip = hs_ip
                if is_detected and hs_ip:
                    self.url = self.auth.build_authenticated_url(f"http://{hs_ip}:{self.port}")
                    self.link_qr = generate_qr_data_uri(self.url)
                else:
                    self.url = None
                    self.link_qr = ""
            snap = self.status_dict()

        if emit and changed:
            self.events.emit({"type": "hotspot_status", **snap})
        return snap

    def refresh_authenticated_url(self) -> None:
        with self._lock:
            if self.detected and self.ip:
                self.url = self.auth.build_authenticated_url(f"http://{self.ip}:{self.port}")
                self.link_qr = generate_qr_data_uri(self.url)
                snap = self.status_dict()
            else:
                return
        self.events.emit({"type": "hotspot_status", **snap})

    def open_windows_hotspot_settings(self) -> dict[str, Any]:
        """Opens Windows Mobile Hotspot settings via ms-settings:network-mobilehotspot (G1)."""
        if os.name != "nt":
            msg = "Windows 10/11 is required to open Mobile Hotspot settings."
            logger.warning(msg)
            self.events.emit({
                "type": "ui_error",
                "code": "HOTSPOT_SETTINGS_ERROR",
                "message": msg,
            })
            return {"ok": False, "error": msg}

        try:
            os.startfile(WINDOWS_HOTSPOT_SETTINGS_URI)  # type: ignore[attr-defined]
            return {"ok": True}
        except Exception as exc:
            msg = f"Could not open Windows Hotspot settings: {exc}"
            logger.warning(msg)
            self.events.emit({
                "type": "ui_error",
                "code": "HOTSPOT_SETTINGS_ERROR",
                "message": msg,
            })
            return {"ok": False, "error": msg}
