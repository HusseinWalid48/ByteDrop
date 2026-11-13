"""Device presence registry, multi-socket grouping, kicking (code 4001), and session block list."""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import threading
from contextlib import suppress
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from bytedrop.state import BlockedDeviceRecord, DeviceEntity

logger = logging.getLogger("bytedrop.devices")

WS_CLOSE_KICKED = 4001


class DeviceRegistry:
    """Manages connected devices, merges multiple sockets per device_id, and enforces session block list."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ws_to_device_id: dict[WebSocket, str] = {}
        self._device_sockets: dict[str, list[WebSocket]] = {}
        self._devices: dict[str, DeviceEntity] = {}
        self._blocked_by_id: dict[str, BlockedDeviceRecord] = {}
        self._blocked_ips: dict[str, str] = {}  # ip -> device_id

    @staticmethod
    def sanitize_device_id(raw_id: str | None) -> str:
        if not raw_id:
            return f"dev-{secrets.token_hex(4)}"
        cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(raw_id))[:48]
        return cleaned or f"dev-{secrets.token_hex(4)}"

    def is_blocked(self, device_id: str | None = None, ip: str | None = None) -> bool:
        with self._lock:
            if device_id and device_id in self._blocked_by_id:
                return True
            return bool(ip and ip in self._blocked_ips)

    async def register_socket(
        self,
        websocket: WebSocket,
        device_id: str,
        ip: str,
        via_tunnel: bool,
        device_name: str | None = None,
    ) -> DeviceEntity:
        clean_id = self.sanitize_device_id(device_id)
        via_label = "Cloud" if via_tunnel else "Wi-Fi"
        friendly = (str(device_name).strip()[:64] if device_name else "") or f"Phone ({ip})"

        with self._lock:
            old_id = self._ws_to_device_id.get(websocket)
            if old_id and old_id != clean_id:
                socks = self._device_sockets.get(old_id, [])
                if websocket in socks:
                    socks.remove(websocket)
                if not socks:
                    self._device_sockets.pop(old_id, None)
                    self._devices.pop(old_id, None)

            self._ws_to_device_id[websocket] = clean_id
            sock_list = self._device_sockets.setdefault(clean_id, [])
            if websocket not in sock_list:
                sock_list.append(websocket)

            existing = self._devices.get(clean_id)
            if existing:
                if device_name:
                    existing.name = friendly
                existing.ip = ip
                existing.via = via_label
                existing.online = True
                dev = existing
            else:
                dev = DeviceEntity(
                    id=clean_id,
                    name=friendly,
                    ip=ip,
                    via=via_label,
                    connected_at=datetime.now().strftime("%H:%M:%S"),
                    online=True,
                )
                self._devices[clean_id] = dev
            return dev

    def unregister_socket(self, websocket: WebSocket) -> str | None:
        with self._lock:
            dev_id = self._ws_to_device_id.pop(websocket, None)
            if not dev_id:
                return None
            socks = self._device_sockets.get(dev_id, [])
            if websocket in socks:
                socks.remove(websocket)
            if not socks:
                self._device_sockets.pop(dev_id, None)
                self._devices.pop(dev_id, None)
            return dev_id

    def get_device_id_for_ws(self, websocket: WebSocket) -> str | None:
        with self._lock:
            return self._ws_to_device_id.get(websocket)

    def get_device(self, device_id: str) -> DeviceEntity | None:
        with self._lock:
            return self._devices.get(device_id)

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [d.to_dict() for d in self._devices.values()]

    def list_blocked(self) -> list[dict[str, Any]]:
        with self._lock:
            return [b.to_dict() for b in self._blocked_by_id.values()]

    def active_device_count(self) -> int:
        with self._lock:
            return len(self._devices)

    async def kick_device(self, device_id: str) -> BlockedDeviceRecord | None:
        """Sends {'type':'kicked'}, closes all sockets for device_id with 4001, and adds to block list."""
        with self._lock:
            dev = self._devices.get(device_id)
            socks = list(self._device_sockets.get(device_id, []))
            dev_name = dev.name if dev else f"Device ({device_id})"
            dev_ip = dev.ip if dev else ""

            record = BlockedDeviceRecord(
                device_id=device_id,
                name=dev_name,
                ip=dev_ip,
                blocked_at=datetime.now().strftime("%H:%M:%S"),
            )
            self._blocked_by_id[device_id] = record
            if dev_ip and dev_ip != "127.0.0.1":
                self._blocked_ips[dev_ip] = device_id

            for ws in socks:
                self._ws_to_device_id.pop(ws, None)
            self._device_sockets.pop(device_id, None)
            self._devices.pop(device_id, None)

        for ws in socks:
            with suppress(Exception):
                await ws.send_json({"type": "kicked", "device_id": device_id, "reason": "Disconnected by the PC"})
            with suppress(Exception):
                await ws.close(code=WS_CLOSE_KICKED, reason="Disconnected by the PC")

        return record

    def unblock_device(self, device_id: str) -> bool:
        """Removes a device from the block list so it can reconnect."""
        with self._lock:
            rec = self._blocked_by_id.pop(device_id, None)
            for ip, did in list(self._blocked_ips.items()):
                if did == device_id:
                    self._blocked_ips.pop(ip, None)
            return rec is not None

    def clear_blocks(self) -> None:
        """Clears all blocked devices (called on session regeneration or restart)."""
        with self._lock:
            self._blocked_by_id.clear()
            self._blocked_ips.clear()

    async def disconnect_all(self, code: int = 1008) -> None:
        with self._lock:
            all_ws = list(self._ws_to_device_id.keys())
            self._ws_to_device_id.clear()
            self._device_sockets.clear()
            self._devices.clear()
        for ws in all_ws:
            with suppress(Exception):
                await ws.close(code=code)

    async def send_to_device(self, device_id: str, message: dict[str, Any]) -> None:
        with self._lock:
            socks = list(self._device_sockets.get(device_id, []))
        for ws in socks:
            try:
                await ws.send_json(message)
            except Exception:
                self.unregister_socket(ws)

    async def broadcast(self, message: dict[str, Any], exclude: WebSocket | None = None) -> None:
        with self._lock:
            all_ws = [ws for ws in self._ws_to_device_id if ws is not exclude]
        if not all_ws:
            return
        results = await asyncio.gather(
            *(ws.send_json(message) for ws in all_ws),
            return_exceptions=True,
        )
        for ws, res in zip(all_ws, results, strict=False):
            if isinstance(res, Exception):
                self.unregister_socket(ws)
