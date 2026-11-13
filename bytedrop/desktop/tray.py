"""System tray icon manager using pystray and Pillow."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from PIL import Image, ImageDraw

from bytedrop import __version__
from bytedrop.paths import get_assets_dir

logger = logging.getLogger("bytedrop.desktop.tray")


def create_tray_image() -> Image.Image:
    ico_path = get_assets_dir() / "bytedrop.ico"
    if ico_path.exists():
        try:
            with Image.open(ico_path) as loaded:
                return loaded.convert("RGBA").copy()
        except Exception as exc:
            logger.debug("Fallback to generated tray image (%s): %s", ico_path, exc)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((4, 4, 60, 60), radius=14, fill=(29, 78, 216, 255))
    draw.polygon(
        [(32, 14), (18, 30), (26, 30), (26, 44), (38, 44), (38, 30), (46, 30)],
        fill=(255, 255, 255, 255),
    )
    draw.rectangle((18, 48, 46, 52), fill=(147, 197, 253, 255))
    return img


class TrayManager:
    """Manages the Windows system tray icon."""

    def __init__(
        self,
        on_show_window: Callable[[], None],
        on_open_downloads: Callable[[], None],
        on_quit_app: Callable[[], None],
    ) -> None:
        self._on_show_window = on_show_window
        self._on_open_downloads = on_open_downloads
        self._on_quit_app = on_quit_app
        self._lock = threading.Lock()
        self.icon: Any = None

    def ensure_running(self) -> None:
        with self._lock:
            if self.icon is not None:
                return
            try:
                import pystray  # type: ignore[import-untyped,import-not-found]
            except Exception as exc:
                logger.warning("pystray not available: %s", exc)
                return

            def handle_show(icon: Any, item: Any) -> None:
                self._on_show_window()

            def handle_downloads(icon: Any, item: Any) -> None:
                self._on_open_downloads()

            def handle_quit(icon: Any, item: Any) -> None:
                self.stop()
                self._on_quit_app()

            menu = pystray.Menu(
                pystray.MenuItem("Open ByteDrop", handle_show, default=True),
                pystray.MenuItem("Open Downloads Folder", handle_downloads),
                pystray.MenuItem("Quit ByteDrop", handle_quit),
            )
            self.icon = pystray.Icon("ByteDrop", create_tray_image(), f"ByteDrop v{str(__version__).lstrip('vV')}", menu)
            threading.Thread(target=self.icon.run, daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            if self.icon is not None:
                try:
                    self.icon.stop()
                except Exception as exc:
                    logger.debug("Tray icon stop warning: %s", exc)
                self.icon = None
