"""Windows toast notification helper using winotify with tray balloon fallback."""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger("bytedrop.desktop.notify")


def send_os_notification(title: str, message: str, enabled: bool = True, tray_icon: Any = None) -> None:
    """Sends a non-blocking OS toast notification on Windows 10/11 when enabled."""
    if not enabled:
        return

    def worker() -> None:
        if os.name == "nt":
            try:
                from winotify import Notification  # type: ignore[import-not-found,import-untyped]

                toast = Notification(
                    app_id="ByteDrop",
                    title=title,
                    msg=message,
                    duration="short",
                )
                toast.show()
                return
            except Exception as exc:
                logger.debug("winotify notification fallback: %s", exc)

        if tray_icon is not None and hasattr(tray_icon, "notify"):
            try:
                tray_icon.notify(message, title)
            except Exception as exc:
                logger.debug("Tray balloon notification fallback: %s", exc)

    threading.Thread(target=worker, daemon=True).start()
