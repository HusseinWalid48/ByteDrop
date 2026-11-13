"""PyWebView desktop window launcher, native drag-and-drop handler, and event dispatcher."""
from __future__ import annotations

import inspect
import json
import logging
import os
import queue
import subprocess
import sys
import threading
from typing import Any

from bytedrop.app import ByteDropApplication
from bytedrop.desktop.api import DesktopApi
from bytedrop.desktop.notify import send_os_notification
from bytedrop.desktop.single_instance import (
    focus_existing_window_win32,
    remove_running_pid,
    start_show_window_listener,
)
from bytedrop.desktop.tray import TrayManager
from bytedrop.paths import get_ui_dir
from bytedrop.server.factory import run_uvicorn
from bytedrop.server.static import compute_asset_version, inject_theme_into_html

logger = logging.getLogger("bytedrop.desktop.window")


def launch_desktop_window(ctx: ByteDropApplication) -> None:
    """Starts the uvicorn server, cloud tunnel, tray, and pywebview desktop window."""
    import webview  # type: ignore[import-untyped,import-not-found]

    ui_dir = get_ui_dir()
    desktop_html_path = ui_dir / "desktop" / "index.html"
    if not desktop_html_path.exists():
        raise RuntimeError(f"Required desktop UI file is missing: {desktop_html_path}")

    asset_version = compute_asset_version(ui_dir)
    raw_html = desktop_html_path.read_text(encoding="utf-8")
    base_tag = f'<base href="http://127.0.0.1:{ctx.port}/">'
    raw_html = raw_html.replace("<head>", f"<head>\n    {base_tag}", 1)
    html = inject_theme_into_html(ctx, raw_html, asset_version, is_desktop=True)

    server_thread = threading.Thread(target=run_uvicorn, args=(ctx,), daemon=True)
    server_thread.start()

    # Start automatic background cloud link if enabled (Section 4)
    if ctx.config.cloud_auto_start:
        ctx.tunnel.start_background()

    force_quit = False
    shutdown_event = threading.Event()
    js_queue: queue.Queue[str] = queue.Queue(maxsize=500)
    window_ref: list[Any] = []

    def open_downloads_folder() -> None:
        folder = ctx.config.upload_dir
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def show_window() -> None:
        if window_ref:
            try:
                window_ref[0].show()
                window_ref[0].restore()
            except Exception as exc:
                logger.debug("Restore window from tray warning: %s", exc)
        focus_existing_window_win32()

    def quit_from_tray() -> None:
        nonlocal force_quit
        force_quit = True
        shutdown_event.set()
        remove_running_pid(ctx.appdata_dir)
        if window_ref:
            try:
                window_ref[0].destroy()
            except Exception as exc:
                logger.debug("Destroy window warning: %s", exc)
        ctx.shutdown()

    tray = TrayManager(
        on_show_window=show_window,
        on_open_downloads=open_downloads_folder,
        on_quit_app=quit_from_tray,
    )
    if ctx.config.tray_mode_enabled or ctx.config.start_minimized:
        tray.ensure_running()

    start_show_window_listener(ctx.appdata_dir, show_window, shutdown_event)

    api = DesktopApi(ctx, on_ensure_tray=tray.ensure_running, on_stop_tray=tray.stop)
    sig = inspect.signature(webview.create_window)
    bg_color = "#eff6ff" if ctx.config.theme == "light" else "#0b1120"
    window_kwargs: dict[str, Any] = {
        "title": f"ByteDrop v{str(ctx.VERSION).lstrip('vV')}",
        "html": html,
        "width": 1000,
        "height": 680,
        "min_size": (900, 620),
        "resizable": True,
        "frameless": False,
        "transparent": False,
        "background_color": bg_color,
        "hidden": bool(ctx.config.start_minimized),
    }
    if "api" in sig.parameters:
        window_kwargs["api"] = api
    else:
        window_kwargs["js_api"] = api

    window = webview.create_window(**window_kwargs)
    window_ref.append(window)

    def enqueue_js(script: str) -> None:
        if shutdown_event.is_set():
            return
        try:
            js_queue.put_nowait(script)
        except queue.Full:
            logger.debug("JS queue full; dropping script dispatch")

    def js_dispatcher_loop() -> None:
        while not shutdown_event.is_set():
            try:
                script = js_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                window.evaluate_js(script)
            except Exception as exc:
                logger.debug("evaluate_js warning: %s", exc)
            finally:
                js_queue.task_done()

    threading.Thread(target=js_dispatcher_loop, daemon=True).start()

    def on_event(event: dict[str, Any]) -> None:
        if shutdown_event.is_set():
            return
        etype = event.get("type")
        if etype == "transfer_updated":
            tr = event.get("transfer") or {}
            if tr.get("state") == "done" and tr.get("direction") == "phone_to_pc":
                fname = tr.get("saved_as") or (tr.get("file") or {}).get("name") or "File"
                cat = (tr.get("file") or {}).get("category") or "Others"
                send_os_notification(
                    "ByteDrop Transfer Complete",
                    f"Saved {fname} to /{cat}",
                    enabled=ctx.config.notifications_enabled,
                    tray_icon=tray.icon,
                )
        enqueue_js(f"window.__onServerEvent && window.__onServerEvent({json.dumps(event)})")

    ctx.events.subscribe_sync(on_event)

    def on_loaded() -> None:
        try:
            from webview.dom import DOMEventHandler  # type: ignore[import-untyped,import-not-found]

            def on_drop(e: dict[str, Any]) -> None:
                if ctx.devices.active_device_count() == 0:
                    enqueue_js("window.__flashWarning && window.__flashWarning('Connect a device first!')")
                    return
                files = e.get("dataTransfer", {}).get("files", [])
                paths: list[str] = []
                missing_full_path = False
                for f in files:
                    if isinstance(f, dict):
                        full_p = f.get("pywebviewFullPath") or f.get("path")
                        if isinstance(full_p, str) and full_p:
                            paths.append(full_p)
                        else:
                            missing_full_path = True
                if paths:
                    api.stage_paths_async(paths)
                elif missing_full_path:
                    enqueue_js(
                        "window.__flashWarning && window.__flashWarning('Folder path not exposed by drag-and-drop; please click Browse Folders.')"
                    )

            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("Failed binding pywebview DOMEventHandler drop: %s", exc)

    window.events.loaded += on_loaded

    def on_closing() -> bool:
        if ctx.config.tray_mode_enabled and not force_quit:
            tray.ensure_running()
            window.hide()
            send_os_notification(
                "ByteDrop Minimized to Tray",
                "ByteDrop is still running in the background.",
                enabled=ctx.config.notifications_enabled,
                tray_icon=tray.icon,
            )
            return False
        return True

    def on_closed() -> None:
        shutdown_event.set()
        remove_running_pid(ctx.appdata_dir)
        tray.stop()
        ctx.shutdown()

    window.events.closing += on_closing
    window.events.closed += on_closed

    debug_mode = os.environ.get("BYTEDROP_DEBUG") == "1"
    try:
        webview.start(debug=debug_mode)
    finally:
        shutdown_event.set()
        remove_running_pid(ctx.appdata_dir)
        tray.stop()
        ctx.shutdown()
        if server_thread.is_alive():
            server_thread.join(timeout=3)
