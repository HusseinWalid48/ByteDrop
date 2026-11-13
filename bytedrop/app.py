"""Central ByteDrop application context, state snapshot builder, and lifecycle orchestrator."""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

import uvicorn

from bytedrop import __version__
from bytedrop.auth import AuthManager
from bytedrop.clipboard import ClipboardManager
from bytedrop.config import ACCENT_PALETTES, ConfigManager
from bytedrop.desktop.autostart import update_windows_startup_registry
from bytedrop.desktop.hotspot import HotspotManager
from bytedrop.devices import DeviceRegistry
from bytedrop.events import EventBus
from bytedrop.fsutil import hide_generated
from bytedrop.history import HistoryStore
from bytedrop.logging_setup import setup_logging
from bytedrop.net import (
    PORT_RANGE_END,
    PORT_RANGE_START,
    NetworkWatcher,
    find_and_bind_free_port,
    generate_qr_data_uri,
    get_candidate_lan_ips,
    select_local_ip,
)
from bytedrop.paths import get_app_dir, get_appdata_dir
from bytedrop.transfers.download import DownloadHandler
from bytedrop.transfers.manager import TransferManager
from bytedrop.transfers.upload import UploadHandler
from bytedrop.tunnel import TunnelManager

logger = logging.getLogger("bytedrop.app")


class ByteDropApplication:
    """Single source of truth for the ByteDrop server and desktop application."""

    VERSION = __version__

    def __init__(self, port: int | None = None, appdata_dir: Path | None = None) -> None:
        self.app_dir = get_app_dir()
        self.appdata_dir = get_appdata_dir(appdata_dir)
        self.auth = AuthManager()
        self.logger = setup_logging(self.appdata_dir, self.auth.get_token)
        self.config = ConfigManager(self.appdata_dir)
        self.events = EventBus()
        self.devices = DeviceRegistry()
        self.history = HistoryStore(self.appdata_dir)

        self.bound_socket: socket.socket | None = None
        if port is not None:
            self.port = port
        else:
            self.port, self.bound_socket = find_and_bind_free_port(
                PORT_RANGE_START,
                PORT_RANGE_END - PORT_RANGE_START + 1,
            )

        self.host = select_local_ip(self.config.preferred_ip)
        self.transfers = TransferManager(self.config, self.events, self.history)
        self.upload_handler = UploadHandler(self.transfers)
        self.download_handler = DownloadHandler(self.transfers)
        self.tunnel = TunnelManager(self.config, self.auth, self.events, self.port)
        self.clipboard = ClipboardManager(self.config, self.events)
        self.hotspot = HotspotManager(self.auth, self.events, self.port)
        self.network_watcher = NetworkWatcher(
            get_preferred_ip=lambda: self.config.preferred_ip,
            on_ip_changed=self._on_network_ip_changed,
        )

        self.uvicorn_server: uvicorn.Server | None = None
        self._expiry_task: asyncio.Task[None] | None = None
        self._summary_task: asyncio.Task[None] | None = None
        self._shutdown_flag = False

        # Subscribe WebSocket broadcast to all EventBus events
        self.events.subscribe_async(self._broadcast_event_to_ws)

    async def _broadcast_event_to_ws(self, event: dict[str, Any]) -> None:
        await self.devices.broadcast(event)

    @property
    def local_url(self) -> str:
        return self.auth.build_authenticated_url(f"http://{self.host}:{self.port}")

    @property
    def local_qr(self) -> str:
        return generate_qr_data_uri(self.local_url)

    def _on_network_ip_changed(self, new_ip: str, candidates: list[dict[str, str]]) -> None:
        self.host = new_ip
        self.hotspot.check_and_update(emit=True)
        self.events.emit({
            "type": "network_changed",
            "host": self.host,
            "local_url": self.local_url,
            "local_qr": self.local_qr,
            "qr_data_uri": self.local_qr,
            "candidate_ips": candidates,
            "hotspot": self.hotspot.status_dict(),
        })

    def set_preferred_ip(self, ip: str) -> dict[str, Any]:
        self.config.update(preferred_ip=str(ip or "").strip())
        candidates = get_candidate_lan_ips()
        new_ip = select_local_ip(self.config.preferred_ip)
        self.network_watcher.current_ip = new_ip
        self.host = new_ip
        self.hotspot.check_and_update(emit=True)
        payload = {
            "type": "network_changed",
            "host": self.host,
            "local_url": self.local_url,
            "local_qr": self.local_qr,
            "qr_data_uri": self.local_qr,
            "candidate_ips": candidates,
            "preferred_ip": self.config.preferred_ip,
            "hotspot": self.hotspot.status_dict(),
        }
        self.events.emit(payload)
        return payload

    def appearance_dict(self) -> dict[str, str]:
        """The desktop app's current look. The phone page follows it (it has no settings of its own)."""
        return {
            "theme": "light" if self.config.theme == "light" else "dark",
            "accent": self.config.accent if self.config.accent in ACCENT_PALETTES else "blue",
            "language": "ar" if self.config.language == "ar" else "en",
        }

    def snapshot(self, is_desktop: bool = False) -> dict[str, Any]:
        """Builds a complete authoritative state snapshot (Section 2.1)."""
        data: dict[str, Any] = {
            "type": "snapshot",
            "version": self.VERSION,
            "seq": self.events.seq,
            "devices": self.devices.list_devices(),
            "blocked_devices": self.devices.list_blocked(),
            "connected_count": self.devices.active_device_count(),
            "transfers": self.transfers.list_transfers(),
            "preparing_items": self.transfers.list_preparing(),
            "activity_summary": self.transfers.get_activity_summary(),
            "shares": self.transfers.list_shares(),
            "history": self.history.list_recent(50),
            "clipboard_text": self.clipboard.current_text,
            "settings": self.config.public_subset(include_desktop_fields=is_desktop),
            "palettes": ACCENT_PALETTES,
            "appearance": self.appearance_dict(),
            "tunnel": self.tunnel.status_dict(),
        }
        if is_desktop:
            self.hotspot.check_and_update(emit=False)
            data.update({
                "host": self.host,
                "port": self.port,
                "local_url": self.local_url,
                "local_qr": self.local_qr,
                "qr_data_uri": self.local_qr,
                "candidate_ips": get_candidate_lan_ips(),
                "hotspot": self.hotspot.status_dict(),
                "corrupt_config_recovered": self.config.corrupt_config_recovered,
            })
        return data

    async def kick_device(self, device_id: str) -> dict[str, Any]:
        """Kicks a device (close 4001), adds to block list, cancels its active transfers, and emits state update."""
        self.transfers.cancel_device_transfers(device_id)
        await self.devices.kick_device(device_id)
        payload = self.events.emit({
            "type": "devices_updated",
            "devices": self.devices.list_devices(),
            "blocked_devices": self.devices.list_blocked(),
            "connected_count": self.devices.active_device_count(),
        })
        return payload

    def unblock_device(self, device_id: str) -> dict[str, Any]:
        """Allows a previously blocked device to reconnect."""
        self.devices.unblock_device(device_id)
        payload = self.events.emit({
            "type": "devices_updated",
            "devices": self.devices.list_devices(),
            "blocked_devices": self.devices.list_blocked(),
            "connected_count": self.devices.active_device_count(),
        })
        return payload

    async def regenerate_session_async(self) -> dict[str, Any]:
        """Rotates session token, clears blocked devices and staged requests, disconnects clients, and updates QRs."""
        self.auth.regenerate()
        self.devices.clear_blocks()
        self.transfers.clear_all_staged()
        await self.devices.disconnect_all(code=1008)
        self.tunnel.refresh_authenticated_url()
        self.hotspot.refresh_authenticated_url()

        payload = self.events.emit({
            "type": "session_regenerated",
            "local_url": self.local_url,
            "local_qr": self.local_qr,
            "qr_data_uri": self.local_qr,
            "tunnel": self.tunnel.status_dict(),
            "hotspot": self.hotspot.status_dict(),
            "devices": self.devices.list_devices(),
            "blocked_devices": self.devices.list_blocked(),
            "connected_count": 0,
        })
        return payload

    def regenerate_session_sync(self, loop: asyncio.AbstractEventLoop | None = None) -> dict[str, Any]:
        active_loop = loop or self.events._loop
        if active_loop and active_loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self.regenerate_session_async(), active_loop)
            try:
                return fut.result(timeout=3.0)
            except Exception as exc:
                logger.warning("regenerate_session_sync timeout: %s", exc)
        self.auth.regenerate()
        self.devices.clear_blocks()
        self.transfers.clear_all_staged()
        self.tunnel.refresh_authenticated_url()
        self.hotspot.refresh_authenticated_url()
        return self.events.emit({
            "type": "session_regenerated",
            "local_url": self.local_url,
            "local_qr": self.local_qr,
            "qr_data_uri": self.local_qr,
            "tunnel": self.tunnel.status_dict(),
            "hotspot": self.hotspot.status_dict(),
            "devices": self.devices.list_devices(),
            "blocked_devices": self.devices.list_blocked(),
            "connected_count": 0,
        })

    def update_autostart_windows(self, enabled: bool) -> bool:
        self.config.update(autostart_windows=bool(enabled))
        update_windows_startup_registry(self.config.autostart_windows)
        return self.config.autostart_windows

    async def start_background_tasks(self) -> None:
        self._shutdown_flag = False
        self.events.set_loop(asyncio.get_running_loop())
        self.network_watcher.start()
        self.clipboard.start_watcher()
        if self._expiry_task is None or self._expiry_task.done():
            self._expiry_task = asyncio.create_task(self._expiry_loop())
        if self._summary_task is None or self._summary_task.done():
            self._summary_task = asyncio.create_task(self._activity_summary_loop())

    async def stop_background_tasks(self) -> None:
        self._shutdown_flag = True
        await self.network_watcher.stop()
        self.clipboard.stop_watcher()
        if self._expiry_task and not self._expiry_task.done():
            self._expiry_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._expiry_task
        if self._summary_task and not self._summary_task.done():
            self._summary_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._summary_task

    async def _expiry_loop(self) -> None:
        while not self._shutdown_flag:
            try:
                await asyncio.sleep(5.0)
                await asyncio.to_thread(self.hotspot.check_and_update, True)
                await asyncio.to_thread(self.transfers.purge_expired)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Expiry loop warning: %s", exc)

    async def _activity_summary_loop(self) -> None:
        """Emits activity_summary at ~4 Hz only while something is active, plus a final idle summary."""
        while not self._shutdown_flag:
            try:
                await asyncio.sleep(0.25)
                self.transfers.emit_activity_summary()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Activity summary loop warning: %s", exc)

    def shutdown(self) -> None:
        self._shutdown_flag = True
        self.clipboard.stop_watcher()
        self.tunnel.stop()
        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        if self.bound_socket:
            with suppress(OSError):
                self.bound_socket.close()
        with suppress(Exception):
            hide_generated(self.app_dir)


_app_singleton: ByteDropApplication | None = None
_singleton_lock = threading.Lock()


def get_application(port: int | None = None, appdata_dir: Path | None = None) -> ByteDropApplication:
    global _app_singleton
    with _singleton_lock:
        if _app_singleton is None:
            _app_singleton = ByteDropApplication(port=port, appdata_dir=appdata_dir)
        return _app_singleton
