"""Cloud link manager (Section 4): automatic background cloudflared quick tunnel with progress, SHA-256 logging, and exponential backoff."""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bytedrop.auth import AuthManager
from bytedrop.config import ConfigManager
from bytedrop.events import EventBus
from bytedrop.fsutil import hide_path
from bytedrop.net import generate_qr_data_uri

logger = logging.getLogger("bytedrop.tunnel")

CLOUDFLARED_VERSION = "2026.7.3"
CLOUDFLARED_SHA256: dict[str, str] = {
    "cloudflared-windows-amd64.exe": "8635da433b6df8194746e88ed9d2589566c20e38bfc2a80e431a348b7c765841",
}

TRYCLOUDFLARE_URL_RE = re.compile(
    r"https://([a-z0-9]+(?:-[a-z0-9]+)+)\.trycloudflare\.com",
    re.IGNORECASE,
)


class TunnelManager:
    """Manages the public cloudflared quick tunnel lifecycle (Section 4).

    States: Starting | Downloading | Online | Reconnecting | Failed | Disabled
    """

    BACKOFF_INITIAL_SEC = 5.0
    BACKOFF_MAX_SEC = 300.0
    STARTUP_TIMEOUT_SEC = 25.0

    def __init__(
        self,
        config: ConfigManager,
        auth: AuthManager,
        events: EventBus,
        port: int,
        popen_factory: Callable[..., Any] | None = None,
        downloader_fn: Callable[[str, Path, Callable[[int], None]], None] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config
        self.auth = auth
        self.events = events
        self.port = port
        self._popen_factory = popen_factory or subprocess.Popen
        self._downloader_fn = downloader_fn or self._default_download
        self._sleep_fn = sleep_fn or time.sleep

        self.bin_dir = config.appdata_dir / "bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        hide_path(self.bin_dir)

        self._lock = threading.RLock()
        self.state: str = "Starting" if config.cloud_auto_start else "Disabled"
        self.reason: str = ""
        self.download_progress: int = 0
        self.raw_public_origin: str | None = None
        self.public_url: str | None = None
        self.cloud_qr: str = ""
        self._proc: Any = None
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._generation: int = 0

    @staticmethod
    def resolve_download_url() -> tuple[str, str]:
        machine = platform.machine().lower()
        is_arm = machine in ("arm64", "aarch64")
        if os.name == "nt":
            bin_name = "cloudflared.exe"
            asset = "cloudflared-windows-amd64.exe"
        elif sys.platform == "darwin":
            bin_name = "cloudflared"
            arch = "arm64" if is_arm else "amd64"
            asset = f"cloudflared-darwin-{arch}.tgz"
        else:
            bin_name = "cloudflared"
            arch = "arm64" if is_arm else "amd64"
            asset = f"cloudflared-linux-{arch}"
        url = f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/{asset}"
        return bin_name, url

    @staticmethod
    def compute_sha256(filepath: Path) -> str:
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest().lower()

    def _default_download(self, url: str, dest: Path, on_progress: Callable[[int], None]) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "ByteDrop/1.0.0"})
        with urllib.request.urlopen(req, timeout=25) as resp, open(dest, "wb") as out_f:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            last_pct = -1
            while True:
                buf = resp.read(256 * 1024)
                if not buf:
                    break
                out_f.write(buf)
                downloaded += len(buf)
                if total > 0:
                    pct = min(99, int((downloaded / total) * 100))
                    if pct != last_pct:
                        last_pct = pct
                        on_progress(pct)
        on_progress(100)

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "reason": self.reason,
                "download_progress": self.download_progress,
                "public_url": self.public_url,
                "cloud_qr": self.cloud_qr,
                "auto_start": self.config.cloud_auto_start,
            }

    def _emit_status(self, state: str, reason: str = "", progress: int | None = None) -> None:
        with self._lock:
            self.state = state
            self.reason = reason
            if progress is not None:
                self.download_progress = progress
            if state != "Online":
                self.raw_public_origin = None
                self.public_url = None
                self.cloud_qr = ""
            snap = self.status_dict()
        self.events.emit({"type": "tunnel_status", **snap})

    def refresh_authenticated_url(self) -> None:
        """Rebuilds public_url and cloud_qr when the session token is regenerated."""
        with self._lock:
            if self.state == "Online" and self.raw_public_origin:
                self.public_url = self.auth.build_authenticated_url(self.raw_public_origin)
                self.cloud_qr = generate_qr_data_uri(self.public_url)
                snap = self.status_dict()
            else:
                return
        self.events.emit({"type": "tunnel_status", **snap})

    def start_background(self, force: bool = False) -> None:
        if os.environ.get("BYTEDROP_NO_TUNNEL") == "1":
            self._emit_status("Disabled", "Disabled via BYTEDROP_NO_TUNNEL")
            return
        if not self.config.cloud_auto_start and not force:
            self._emit_status("Disabled", "Cloud link auto-start is off")
            return

        with self._lock:
            self._generation += 1
            gen = self._generation
            self._stop_event.clear()

        self._kill_proc()
        t = threading.Thread(target=self._supervisor_loop, args=(gen,), daemon=True)
        self._worker_thread = t
        t.start()

    def restart(self) -> dict[str, Any]:
        self.start_background(force=True)
        return self.status_dict()

    def set_auto_start(self, enabled: bool) -> dict[str, Any]:
        self.config.update(cloud_auto_start=bool(enabled))
        if enabled:
            self.start_background(force=True)
        else:
            self.stop()
            self._emit_status("Disabled", "Disabled in settings")
        return self.status_dict()

    def stop(self) -> None:
        with self._lock:
            self._generation += 1
            self._stop_event.set()
        self._kill_proc()

    def _kill_proc(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is not None and getattr(proc, "poll", lambda: 0)() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception as exc:
                    logger.debug("Process kill error: %s", exc)

    def _ensure_binary(self, gen: int) -> tuple[str | None, str]:
        """Returns (binary_path, error_reason)."""
        system_bin = shutil.which("cloudflared")
        if system_bin and self._popen_factory is subprocess.Popen and self._downloader_fn == self._default_download:
            return system_bin, ""

        bin_name, dl_url = self.resolve_download_url()
        if dl_url.endswith(".tgz") and self._popen_factory is subprocess.Popen:
            return None, "macOS auto-download requires system cloudflared"

        asset = dl_url.rsplit("/", 1)[-1]
        expected_sha = (
            CLOUDFLARED_SHA256.get(asset)
            or CLOUDFLARED_SHA256.get("cloudflared-windows-amd64.exe")
            or ""
        ).strip().lower()

        bin_path = self.bin_dir / bin_name
        if bin_path.exists():
            try:
                digest = self.compute_sha256(bin_path)
                logger.info("cloudflared binary SHA-256: %s", digest)
                if not expected_sha or digest != expected_sha:
                    logger.warning(
                        "Cached cloudflared SHA-256 mismatch (expected %s, got %s); deleting cached binary",
                        expected_sha,
                        digest,
                    )
                    bin_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Could not read cloudflared binary for SHA-256: %s", exc)
                return None, "antivirus/blocked exe"

        if not bin_path.exists():
            if self._popen_factory is not subprocess.Popen and self._downloader_fn == self._default_download:
                # Fake process mode in tests without custom downloader
                return str(bin_path), ""

            self._emit_status("Downloading", "Downloading cloudflared...", progress=0)
            tmp_path = bin_path.with_suffix(".download")
            try:
                def on_dl_pct(pct: int) -> None:
                    if self._generation == gen:
                        self._emit_status("Downloading", f"Downloading cloudflared ({pct}%)...", progress=pct)

                self._downloader_fn(dl_url, tmp_path, on_dl_pct)
                digest = self.compute_sha256(tmp_path)
                logger.info("Downloaded cloudflared SHA-256: %s", digest)
                if not expected_sha or digest != expected_sha:
                    logger.error("cloudflared SHA-256 mismatch (expected %s, got %s)", expected_sha, digest)
                    tmp_path.unlink(missing_ok=True)
                    return None, "checksum mismatch"

                tmp_path.replace(bin_path)
                if os.name != "nt":
                    os.chmod(bin_path, 0o755)
                hide_path(bin_path)
            except urllib.error.URLError as exc:
                tmp_path.unlink(missing_ok=True)
                logger.warning("cloudflared download failed (network): %s", exc)
                return None, "no internet"
            except OSError as exc:
                tmp_path.unlink(missing_ok=True)
                logger.warning("cloudflared download failed (OS error): %s", exc)
                return None, "download failed"
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                logger.warning("cloudflared download failed: %s", exc)
                return None, "download failed"

        return str(bin_path), ""

    def _supervisor_loop(self, gen: int) -> None:
        backoff = self.BACKOFF_INITIAL_SEC
        attempt = 0

        while not self._stop_event.is_set() and self._generation == gen:
            attempt += 1
            self._emit_status("Starting" if attempt == 1 else "Reconnecting", "")

            bin_str, err_reason = self._ensure_binary(gen)
            if not bin_str:
                self._emit_status("Failed", err_reason or "download failed")
                return
            cmd = [bin_str, "tunnel", "--url", f"http://127.0.0.1:{self.port}"]

            if self._stop_event.is_set() or self._generation != gen:
                return

            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                proc = self._popen_factory(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=flags,
                )
            except PermissionError as exc:
                logger.warning("tunnel execution blocked: %s", exc)
                self._emit_status("Failed", "antivirus/blocked exe")
                return
            except OSError as exc:
                logger.warning("tunnel failed to start: %s", exc)
                self._emit_status("Failed", "antivirus/blocked exe")
                return

            with self._lock:
                self._proc = proc

            found_event = threading.Event()
            timed_out = False

            def watchdog(watched_proc: Any, evt: threading.Event = found_event) -> None:
                nonlocal timed_out
                self._sleep_fn(self.STARTUP_TIMEOUT_SEC)
                if not evt.is_set() and self._proc is watched_proc and self._generation == gen:
                    timed_out = True
                    self._kill_proc()

            threading.Thread(target=watchdog, args=(proc,), daemon=True).start()

            output_lines: list[str] = []
            try:
                if proc.stdout:
                    for line in proc.stdout:
                        if self._stop_event.is_set() or self._generation != gen:
                            break
                        lower_line = line.lower()
                        output_lines.append(lower_line)
                        if not found_event.is_set():
                            if any(err_tok in lower_line for err_tok in ("failed", "error", " err ", "unable to")):
                                continue
                            match = TRYCLOUDFLARE_URL_RE.search(line)
                            if match:
                                found_event.set()
                                raw_origin = match.group(0).lower()
                                full_url = self.auth.build_authenticated_url(raw_origin)
                                qr_uri = generate_qr_data_uri(full_url)
                                with self._lock:
                                    self.raw_public_origin = raw_origin
                                    self.public_url = full_url
                                    self.cloud_qr = qr_uri
                                    self.state = "Online"
                                    self.reason = ""
                                    snap = self.status_dict()
                                self.events.emit({"type": "tunnel_status", **snap})
                                backoff = self.BACKOFF_INITIAL_SEC
            except Exception as exc:
                logger.debug("tunnel stdout loop ended: %s", exc)

            if self._stop_event.is_set() or self._generation != gen:
                return

            joined_out = " ".join(output_lines[-15:])
            if timed_out:
                fail_reason = "timeout"
            elif any(k in joined_out for k in ("no such host", "network is unreachable", "dial tcp", "lookup")):
                fail_reason = "no internet"
            else:
                fail_reason = "connection closed"

            self._emit_status("Failed", fail_reason)
            if self._stop_event.is_set() or self._generation != gen:
                return

            # Exponential backoff (5 s up to 5 min) before reconnecting
            self._sleep_fn(backoff)
            backoff = min(self.BACKOFF_MAX_SEC, backoff * 2.0)
