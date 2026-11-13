"""Rotating file logging setup in %APPDATA%\\ByteDrop\\bytedrop.log, crash hooks, and diagnostics builder."""
from __future__ import annotations

import logging
import platform
import sys
import threading
import time
import traceback
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any

from bytedrop.fsutil import hide_path


def redact_token(text: str, token: str) -> str:
    """Redacts any occurrence of the session token from text."""
    if not text:
        return ""
    if token and len(token) >= 6 and token in text:
        return text.replace(token, "[REDACTED]")
    return text


class TokenRedactingFilter(logging.Filter):
    """Ensures the session token never appears in any log message."""

    def __init__(self, get_token_fn: Callable[[], str]) -> None:
        super().__init__()
        self._get_token = get_token_fn

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            token = self._get_token()
            msg = redact_token(record.getMessage(), token)
            record.msg = msg
            record.args = ()
        except Exception:
            return True
        return True


def install_crash_handlers(appdata_dir: Path, get_token_fn: Callable[[], str]) -> None:
    """Installs sys.excepthook and threading.excepthook writing redacted tracebacks to crash.log and bytedrop.log."""
    crash_path = appdata_dir / "crash.log"
    log = logging.getLogger("bytedrop.crash")

    def _record_crash(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
        thread_name: str = "MainThread",
    ) -> None:
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            return
        try:
            token = get_token_fn()
        except Exception:
            token = ""
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        safe_tb = redact_token(tb_text, token)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"=== Unhandled Exception [{stamp}] ({thread_name}) ===\n{safe_tb}\n"
        log.critical("Unhandled exception in %s:\n%s", thread_name, safe_tb)
        try:
            with open(crash_path, "a", encoding="utf-8") as fh:
                fh.write(entry)
            hide_path(crash_path)
        except OSError as io_exc:
            log.debug("Could not write crash.log: %s", io_exc)

    def _sys_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        _record_crash(exc_type, exc_value, exc_tb, "MainThread")

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            return
        t_name = args.thread.name if args.thread else "WorkerThread"
        _record_crash(args.exc_type, args.exc_value, args.exc_traceback, t_name)

    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook


def setup_logging(appdata_dir: Path, get_token_fn: Callable[[], str]) -> logging.Logger:
    """Configures the root 'bytedrop' logger writing to %APPDATA%\\ByteDrop\\bytedrop.log."""
    log_path = appdata_dir / "bytedrop.log"
    logger = logging.getLogger("bytedrop")
    logger.setLevel(logging.INFO)

    # Remove existing handlers if re-initialized in tests
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()

    try:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        handler.setFormatter(fmt)
        handler.addFilter(TokenRedactingFilter(get_token_fn))
        logger.addHandler(handler)
        hide_path(log_path)
    except OSError:
        logger.addHandler(logging.NullHandler())

    install_crash_handlers(appdata_dir, get_token_fn)
    return logger


def get_diagnostics_text(ctx: Any) -> str:
    """Builds a token-redacted diagnostic report including version, OS, network, and recent log lines."""
    try:
        token = ctx.auth.get_token()
    except Exception:
        token = ""

    tunnel_st = ctx.tunnel.status_dict() if hasattr(ctx, "tunnel") else {}
    hotspot_st = ctx.hotspot.status_dict() if hasattr(ctx, "hotspot") else {}
    log_path = Path(ctx.appdata_dir) / "bytedrop.log"
    tail_lines: list[str] = []
    if log_path.exists():
        try:
            all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail_lines = [redact_token(line, token) for line in all_lines[-40:]]
        except OSError:
            tail_lines = ["(Could not read bytedrop.log)"]

    lines = [
        f"ByteDrop Diagnostics Report (v{getattr(ctx, 'VERSION', 'unknown')})",
        f"Platform: {platform.platform()} ({platform.python_implementation()} {platform.python_version()})",
        f"Frozen: {bool(getattr(sys, 'frozen', False))}",
        f"Local Bind: {getattr(ctx, 'host', 'unknown')}:{getattr(ctx, 'port', 0)}",
        f"Preferred IP: {getattr(ctx.config, 'preferred_ip', '') or 'auto'}",
        f"Cloud Link State: {tunnel_st.get('state', 'Unknown')} ({tunnel_st.get('reason', '')})",
        f"Hotspot Detected: {bool(hotspot_st.get('detected', False))} ({hotspot_st.get('ip', '')})",
        f"Connected Devices: {ctx.devices.active_device_count() if hasattr(ctx, 'devices') else 0}",
        f"Upload Directory: {getattr(ctx.config, 'upload_dir', '')}",
        f"AppData Directory: {getattr(ctx, 'appdata_dir', '')}",
        f"Corrupt Config Recovered: {bool(getattr(ctx.config, 'corrupt_config_recovered', False))}",
        "--- Recent Log Lines (Redacted) ---",
        *tail_lines,
    ]
    return redact_token("\n".join(lines), token)

