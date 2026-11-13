"""ByteDrop v1.0.0 — Thin entry point (bytecode suppression, early single-instance lock + PID file, and lazy app launch)."""
from __future__ import annotations

import atexit
import logging
import os
import sys

# A windowed exe (and pythonw) has no console: sys.stdout / sys.stderr are None. Give them a sink
# before any library tries to write or call isatty() on them.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

from bytedrop.desktop.single_instance import (
    acquire_single_instance_lock,
    remove_running_pid,
    signal_existing_instance,
    write_running_pid,
)
from bytedrop.fsutil import hide_generated
from bytedrop.paths import get_app_dir, get_appdata_dir

sys.dont_write_bytecode = True
logger = logging.getLogger("bytedrop.main")


def _show_error_box(message: str) -> None:
    """Shows a native error dialog on Windows (a windowed exe has no console to print to)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "ByteDrop", 0x10)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        logger.exception("Could not show the error dialog")


def main() -> None:
    app_dir = get_app_dir()
    os.chdir(app_dir)
    appdata_dir = get_appdata_dir()

    # G5 & H5: Acquire single-instance lock BEFORE heavy imports; if already running, signal existing window/tray
    if not acquire_single_instance_lock(appdata_dir):
        signal_existing_instance(appdata_dir)
        logger.info("ByteDrop is already running; signaled existing instance.")
        return

    write_running_pid(appdata_dir)
    atexit.register(remove_running_pid, appdata_dir)
    atexit.register(hide_generated, app_dir)

    # Hide any generated artifacts in the program folder at startup (Section 3.5)
    hide_generated(app_dir)

    from bytedrop.app import get_application
    from bytedrop.desktop.window import launch_desktop_window
    from bytedrop.server.factory import run_uvicorn

    ctx = get_application(appdata_dir=appdata_dir)
    if "--headless-server" in sys.argv:
        try:
            if ctx.config.cloud_auto_start:
                ctx.tunnel.start_background()
            run_uvicorn(ctx)
        finally:
            remove_running_pid(appdata_dir)
            ctx.shutdown()
    else:
        try:
            launch_desktop_window(ctx)
        except Exception:
            logger.exception("ByteDrop could not start its window")
            _show_error_box(
                "ByteDrop could not start its window.\n\n"
                "Make sure the Microsoft Edge WebView2 Runtime is installed, then try again.\n\n"
                f"Details are in:\n{appdata_dir / 'bytedrop.log'}"
            )
            raise


if __name__ == "__main__":
    main()
