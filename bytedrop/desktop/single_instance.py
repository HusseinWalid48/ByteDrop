"""Single-instance mutex lock, Global\\ByteDropShowWindow event signaling, and running.pid management."""
from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bytedrop import __version__
from bytedrop.fsutil import hide_path

logger = logging.getLogger("bytedrop.desktop.single_instance")

SHOW_WINDOW_EVENT_NAMES = ("Global\\ByteDropShowWindow", "Local\\ByteDropShowWindow")
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000

_single_instance_handle: Any = None
_show_event_handle: Any = None
_lock_file_handle: Any = None


def write_running_pid(appdata_dir: Path) -> Path:
    """Writes the current process PID to %APPDATA%\\ByteDrop\\running.pid."""
    pid_path = appdata_dir / "running.pid"
    try:
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        hide_path(pid_path)
    except OSError as exc:
        logger.warning("Failed to write running.pid: %s", exc)
    return pid_path


def remove_running_pid(appdata_dir: Path) -> None:
    """Removes %APPDATA%\\ByteDrop\\running.pid if owned by the current process."""
    pid_path = appdata_dir / "running.pid"
    try:
        if pid_path.exists():
            current = pid_path.read_text(encoding="utf-8").strip()
            if current == str(os.getpid()):
                pid_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("Failed to remove running.pid: %s", exc)


def focus_existing_window_win32() -> bool:
    """Attempts to restore and bring an existing ByteDrop top-level window to the foreground on Windows."""
    if os.name != "nt":
        return False
    try:
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return False
        user32 = windll.user32
        for title in (f"ByteDrop v{str(__version__).lstrip('vV')}", "ByteDrop"):
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                return True
    except Exception as exc:
        logger.debug("Failed focusing existing ByteDrop window: %s", exc)
    return False


def signal_existing_instance(appdata_dir: Path) -> bool:
    """Signals a running ByteDrop instance (including when minimized to tray) to restore and focus its window."""
    signaled = False
    sig_file = appdata_dir / "show_window.signal"
    try:
        appdata_dir.mkdir(parents=True, exist_ok=True)
        sig_file.write_text(str(time.time()), encoding="utf-8")
        hide_path(sig_file)
        signaled = True
    except OSError as exc:
        logger.debug("Could not write show_window.signal: %s", exc)

    if os.name == "nt":
        try:
            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                kernel32 = windll.kernel32
                for ev_name in SHOW_WINDOW_EVENT_NAMES:
                    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, ev_name)
                    if handle:
                        kernel32.SetEvent(handle)
                        kernel32.CloseHandle(handle)
                        signaled = True
        except Exception as exc:
            logger.debug("OpenEventW/SetEvent failed: %s", exc)
        if focus_existing_window_win32():
            signaled = True

    return signaled


def start_show_window_listener(
    appdata_dir: Path,
    on_show_window: Callable[[], None],
    stop_event: threading.Event | None = None,
) -> threading.Thread:
    """Starts a daemon thread watching Global\\ByteDropShowWindow and show_window.signal to restore the window."""
    global _show_event_handle
    sig_file = appdata_dir / "show_window.signal"
    with_suppress = sig_file.exists()
    if with_suppress:
        try:
            sig_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug("Initial show_window.signal unlink failed: %s", exc)

    win_event_handle: Any = None
    if os.name == "nt":
        try:
            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                kernel32 = windll.kernel32
                for ev_name in SHOW_WINDOW_EVENT_NAMES:
                    handle = kernel32.CreateEventW(None, False, False, ev_name)
                    if handle:
                        win_event_handle = handle
                        _show_event_handle = handle
                        break
        except Exception as exc:
            logger.debug("CreateEventW for show-window listener failed: %s", exc)

    def _listener_loop() -> None:
        while stop_event is None or not stop_event.is_set():
            triggered = False
            if win_event_handle is not None and os.name == "nt":
                try:
                    windll = getattr(ctypes, "windll", None)
                    if windll is not None:
                        res = windll.kernel32.WaitForSingleObject(win_event_handle, 250)
                        if res == WAIT_OBJECT_0:
                            triggered = True
                except Exception as exc:
                    logger.debug("WaitForSingleObject warning: %s", exc)
                    time.sleep(0.25)
            else:
                time.sleep(0.25)

            if sig_file.exists():
                try:
                    sig_file.unlink(missing_ok=True)
                except OSError as exc:
                    logger.debug("Failed unlinking show_window.signal: %s", exc)
                triggered = True

            if triggered:
                try:
                    on_show_window()
                except Exception as exc:
                    logger.warning("on_show_window callback error: %s", exc)

    thread = threading.Thread(target=_listener_loop, name="ByteDropShowWindowListener", daemon=True)
    thread.start()
    return thread


def acquire_single_instance_lock(appdata_dir: Path) -> bool:
    """Acquires a single-instance lock across Windows (Named Mutex) and POSIX (flock)."""
    global _single_instance_handle, _lock_file_handle
    if os.name == "nt":
        try:
            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                kernel32 = windll.kernel32
                mutex = kernel32.CreateMutexW(None, False, "Local\\ByteDropSingleInstanceMutex")
                last_err = kernel32.GetLastError()
                if last_err == 183:  # ERROR_ALREADY_EXISTS
                    signal_existing_instance(appdata_dir)
                    return False
                _single_instance_handle = mutex
                return True
        except Exception as exc:
            logger.warning("Named mutex check failed: %s", exc)

    lock_path = appdata_dir / "bytedrop.lock"
    try:
        fh = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115
        if os.name != "nt":
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        hide_path(lock_path)
        _lock_file_handle = fh
        return True
    except Exception as exc:
        logger.warning("Another ByteDrop instance is already running: %s", exc)
        signal_existing_instance(appdata_dir)
        return False

