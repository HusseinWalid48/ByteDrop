"""Thin pywebview JS API bridge delegating commands to ByteDropApplication managers."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import Any

from bytedrop.app import ByteDropApplication
from bytedrop.net import generate_qr_data_uri

logger = logging.getLogger("bytedrop.desktop.api")


def _resolve_dialog_type(webview_mod: Any, kind: str) -> Any:
    file_dialog_enum = getattr(webview_mod, "FileDialog", None)
    if file_dialog_enum is not None:
        if kind == "open" and hasattr(file_dialog_enum, "OPEN"):
            return file_dialog_enum.OPEN
        if kind == "folder" and hasattr(file_dialog_enum, "FOLDER"):
            return file_dialog_enum.FOLDER
    return getattr(webview_mod, "OPEN_DIALOG" if kind == "open" else "FOLDER_DIALOG")


class DesktopApi:
    """Methods exposed to the desktop pywebview UI via window.pywebview.api.*."""

    def __init__(
        self,
        ctx: ByteDropApplication,
        on_ensure_tray: Callable[[], None] | None = None,
        on_stop_tray: Callable[[], None] | None = None,
    ) -> None:
        self._ctx = ctx
        self._on_ensure_tray = on_ensure_tray
        self._on_stop_tray = on_stop_tray

    def get_snapshot(self) -> dict[str, Any]:
        return self._ctx.snapshot(is_desktop=True)

    def get_initial_state(self) -> dict[str, Any]:
        return self._ctx.snapshot(is_desktop=True)

    def stage_paths_async(self, paths: list[str]) -> dict[str, Any]:
        """Runs PC file/folder staging on a background thread and returns immediately."""
        clean_paths = [str(p) for p in (paths or []) if p]
        if not clean_paths:
            return {"status": "empty"}

        def worker() -> None:
            try:
                self._ctx.transfers.stage_pc_paths(clean_paths)
            except Exception as exc:
                logger.error("stage_pc_paths error: %s", exc)
                self._ctx.events.emit({"type": "ui_error", "message": f"Staging failed: {exc}"})

        threading.Thread(target=worker, daemon=True).start()
        return {"status": "scanning"}

    def browse_files(self) -> dict[str, Any]:
        import webview  # type: ignore[import-untyped,import-not-found]

        if not webview.windows:
            return {"status": "empty"}
        dlg_type = _resolve_dialog_type(webview, "open")
        selected = webview.windows[0].create_file_dialog(dlg_type, allow_multiple=True)
        if not selected:
            return {"status": "empty"}
        paths = [selected] if isinstance(selected, str) else list(selected)
        return self.stage_paths_async(paths)

    def browse_folders(self) -> dict[str, Any]:
        import webview  # type: ignore[import-untyped,import-not-found]

        if not webview.windows:
            return {"status": "empty"}
        dlg_type = _resolve_dialog_type(webview, "folder")
        selected = webview.windows[0].create_file_dialog(dlg_type, allow_multiple=True)
        if not selected:
            return {"status": "empty"}
        paths = [selected] if isinstance(selected, str) else list(selected)
        return self.stage_paths_async(paths)

    def handle_drop(self, items: list[Any]) -> dict[str, Any]:
        if not items or not isinstance(items, list):
            return {"status": "empty"}
        resolved: list[str] = []
        for item in items:
            if isinstance(item, str) and item:
                resolved.append(item)
            elif isinstance(item, dict):
                p = item.get("path") or item.get("pywebviewFullPath")
                if isinstance(p, str) and p:
                    resolved.append(p)
        if not resolved:
            return {"status": "empty", "hint": "folder_drop_use_browse"}
        return self.stage_paths_async(resolved)

    def accept_request(self, request_id: str) -> dict[str, Any] | None:
        return self._ctx.transfers.accept_request(str(request_id), accepting_device_id="pc", by_pc=True)

    def reject_request(self, request_id: str) -> dict[str, Any] | None:
        return self._ctx.transfers.reject_request(str(request_id), rejected_by="pc", by_pc=True)

    def respond_transfer(self, request_id: str, accepted: bool) -> dict[str, Any] | None:
        if accepted:
            return self.accept_request(request_id)
        return self.reject_request(request_id)

    def pause_transfer(self, transfer_id: str) -> dict[str, Any] | None:
        return self._ctx.transfers.pause_transfer(str(transfer_id))

    def resume_transfer(self, transfer_id: str) -> dict[str, Any] | None:
        return self._ctx.transfers.resume_transfer(str(transfer_id))

    def cancel_transfer(self, transfer_id: str) -> dict[str, Any] | None:
        return self._ctx.transfers.cancel_any(str(transfer_id), cancelled_by="pc")

    def cancel_prepare(self, request_id: str) -> dict[str, Any] | None:
        return self._ctx.transfers.cancel_any(str(request_id), cancelled_by="pc")

    def cancel_all_transfers(self) -> dict[str, Any]:
        return self._ctx.transfers.cancel_all_transfers(device_id=None, cancelled_by="pc")

    def remove_share(self, share_id: str) -> bool:
        return self._ctx.transfers.remove_share(str(share_id))

    def kick_device(self, device_id: str) -> dict[str, Any]:
        loop = self._ctx.events._loop
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._ctx.kick_device(str(device_id)), loop)
            try:
                return fut.result(timeout=3.0)
            except Exception as exc:
                logger.warning("kick_device error: %s", exc)
        return {"status": "error"}

    def unblock_device(self, device_id: str) -> dict[str, Any]:
        return self._ctx.unblock_device(str(device_id))

    def clear_history(self) -> dict[str, str]:
        self._ctx.history.clear()
        self._ctx.events.emit({"type": "history_cleared"})
        return {"status": "cleared"}

    def open_downloads(self) -> None:
        folder = self._ctx.config.upload_dir
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def choose_download_dir(self) -> dict[str, str]:
        import webview  # type: ignore[import-untyped,import-not-found]

        if not webview.windows:
            return {"path": str(self._ctx.config.upload_dir)}
        dlg_type = _resolve_dialog_type(webview, "folder")
        selected = webview.windows[0].create_file_dialog(dlg_type, allow_multiple=False)
        if not selected:
            return {"path": str(self._ctx.config.upload_dir)}
        folder_path = selected[0] if isinstance(selected, (list, tuple)) else str(selected)
        updated = self._ctx.config.set_upload_dir(folder_path)
        self._ctx.events.emit({
            "type": "settings_updated",
            "settings": self._ctx.config.public_subset(include_desktop_fields=False),
        })
        return {"path": updated}

    def set_ui_preferences(self, theme: str = "", accent: str = "", language: str = "") -> dict[str, Any]:
        """Saves the appearance in config.json and pushes it to the phone page(s), which only follow the app."""
        self._ctx.config.update(
            theme=theme if theme else None,
            accent=accent if accent else None,
            language=language if language else None,
        )
        self._ctx.events.emit({"type": "appearance_updated", "appearance": self._ctx.appearance_dict()})
        return self._ctx.config.public_subset(include_desktop_fields=True)

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(updates, dict):
            return self._ctx.config.public_subset(include_desktop_fields=True)
        if "preferred_ip" in updates:
            self._ctx.set_preferred_ip(str(updates.pop("preferred_ip") or ""))
        if "cloud_auto_start" in updates:
            self._ctx.tunnel.set_auto_start(bool(updates.pop("cloud_auto_start")))
        if "autostart_windows" in updates:
            self._ctx.update_autostart_windows(bool(updates.pop("autostart_windows")))
        if "tray_mode_enabled" in updates:
            enabled = bool(updates["tray_mode_enabled"])
            if enabled and self._on_ensure_tray:
                self._on_ensure_tray()
            elif not enabled and self._on_stop_tray:
                self._on_stop_tray()
        if updates:
            self._ctx.config.update(**updates)
            if any(k in updates for k in ("theme", "accent", "language")):
                self._ctx.events.emit({"type": "appearance_updated", "appearance": self._ctx.appearance_dict()})
        return self._ctx.config.public_subset(include_desktop_fields=True)

    def set_preferred_ip(self, ip: str) -> dict[str, Any]:
        return self._ctx.set_preferred_ip(ip)

    def set_cloud_auto_start(self, enabled: bool) -> dict[str, Any]:
        return self._ctx.tunnel.set_auto_start(bool(enabled))

    def restart_cloud_link(self) -> dict[str, Any]:
        return self._ctx.tunnel.restart()

    def set_clipboard_sync(self, enabled: bool) -> bool:
        return self._ctx.clipboard.set_enabled(bool(enabled))

    def send_text(self, content: str) -> None:
        self._ctx.clipboard.push_text(str(content or ""), source="pc")

    def regenerate_session(self) -> dict[str, Any]:
        return self._ctx.regenerate_session_sync()

    def open_hotspot_settings(self) -> dict[str, Any]:
        return self._ctx.hotspot.open_windows_hotspot_settings()

    def open_log_folder(self) -> dict[str, str]:
        folder = self._ctx.appdata_dir
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return {"status": "opened", "path": str(folder)}
        except Exception as exc:
            logger.warning("Failed opening log folder %s: %s", folder, exc)
            return {"status": "error", "path": str(folder)}

    def open_data_folder(self) -> dict[str, str]:
        return self.open_log_folder()

    def get_diagnostics(self) -> dict[str, str]:
        from bytedrop.logging_setup import get_diagnostics_text

        return {"diagnostics": get_diagnostics_text(self._ctx)}

    def generate_qr(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return ""
        return generate_qr_data_uri(text)

