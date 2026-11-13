"""Plaintext clipboard watcher and sync manager (Section 3.6: opt-in toggle default Off, 1 MB limit, no echo loops)."""
from __future__ import annotations

import ctypes
import logging
import os
import re
import threading
from typing import Any

from bytedrop.config import ConfigManager
from bytedrop.events import EventBus

logger = logging.getLogger("bytedrop.clipboard")

MAX_CLIPBOARD_CHARS = 1_000_000
SECRET_CLIP_RE = re.compile(
    r"(?:^gh[pousr]_[A-Za-z0-9_]{20,}$|^sk-[A-Za-z0-9_-]{20,}$|^AIza[0-9A-Za-z_-]{30,}$|^eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$)"
)


def is_windows_clipboard_excluded() -> bool:
    """Checks if a password manager marked the current Windows clipboard with exclusion formats."""
    if os.name != "nt":
        return False
    try:
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return False
        user32 = windll.user32
        if not user32.OpenClipboard(None):
            return False
        try:
            for fmt_name in (
                "ExcludeClipboardContentFromMonitorProcessing",
                "CanIncludeInClipboardHistory",
                "ClipboardHistoryExclude",
            ):
                fmt_id = user32.RegisterClipboardFormatW(fmt_name)
                if fmt_id and user32.IsClipboardFormatAvailable(fmt_id):
                    return True
        finally:
            user32.CloseClipboard()
    except Exception as exc:
        logger.debug("Clipboard exclusion check failed: %s", exc)
    return False


def looks_like_secret_clipboard(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if SECRET_CLIP_RE.match(stripped):
        return True
    if " " not in stripped and "\n" not in stripped and 28 <= len(stripped) <= 128:
        has_upper = any(c.isupper() for c in stripped)
        has_lower = any(c.islower() for c in stripped)
        has_digit = any(c.isdigit() for c in stripped)
        if has_upper and has_lower and has_digit:
            return True
    return False


class ClipboardManager:
    """Watches the system clipboard when enabled and synchronizes plain text across PC and phones."""

    def __init__(self, config: ConfigManager, events: EventBus) -> None:
        self.config = config
        self.events = events
        self._lock = threading.Lock()
        self.current_text: str = ""
        self._last_system_value: str = ""
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def set_enabled(self, enabled: bool) -> bool:
        self.config.update(clipboard_sync_enabled=bool(enabled))
        self.events.emit({
            "type": "settings_updated",
            "settings": self.config.public_subset(include_desktop_fields=True),
        })
        return self.config.clipboard_sync_enabled

    def write_system_clipboard(self, text: str) -> None:
        with self._lock:
            self._last_system_value = text
            self.current_text = text
            try:
                import pyperclip  # type: ignore[import-untyped,import-not-found]

                pyperclip.copy(text)
            except Exception as exc:
                logger.debug("System clipboard write skipped: %s", exc)

    def push_text(self, content: str, source: str = "pc") -> dict[str, Any] | None:
        """Updates clipboard state and emits text_sync event without echo loops."""
        if not isinstance(content, str) or len(content) > MAX_CLIPBOARD_CHARS:
            return None
        with self._lock:
            if content == self.current_text:
                return None
            self.current_text = content
            self._last_system_value = content

        if source == "pc" or (source == "mobile" and self.config.clipboard_sync_enabled):
            self.write_system_clipboard(content)

        return self.events.emit({
            "type": "text_sync",
            "content": content,
            "source": source,
        })

    def start_watcher(self) -> None:
        self._stop_event.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()

    def stop_watcher(self) -> None:
        self._stop_event.set()

    def _poll_loop(self) -> None:
        try:
            import pyperclip  # type: ignore[import-untyped,import-not-found]

            self._last_system_value = pyperclip.paste() or ""
        except Exception:
            self._last_system_value = ""

        while not self._stop_event.wait(0.75):
            if not self.config.clipboard_sync_enabled:
                continue
            try:
                if is_windows_clipboard_excluded():
                    continue
                import pyperclip  # type: ignore[import-untyped,import-not-found]

                current = pyperclip.paste()
                if isinstance(current, str) and current and len(current) <= MAX_CLIPBOARD_CHARS:
                    with self._lock:
                        changed = current != self._last_system_value
                        if changed:
                            self._last_system_value = current
                            self.current_text = current
                    if changed:
                        if looks_like_secret_clipboard(current):
                            logger.info("Skipped auto-syncing secret-like clipboard content")
                            continue
                        self.events.emit({
                            "type": "text_sync",
                            "content": current,
                            "source": "pc_clipboard",
                        })
            except Exception as exc:
                logger.debug("Clipboard poll warning: %s", exc)
