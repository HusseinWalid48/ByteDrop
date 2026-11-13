"""Network discovery, physical LAN IP selection, pre-bound socket creation, QR generation, and 5s watcher."""
from __future__ import annotations

import asyncio
import base64
import io
import ipaddress
import logging
import socket
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import psutil  # type: ignore[import-untyped]
import qrcode  # type: ignore[import-untyped]

logger = logging.getLogger("bytedrop.net")

PORT_RANGE_START = 8000
PORT_RANGE_END = 8049

VIRTUAL_ADAPTER_KEYWORDS = (
    "virtualbox",
    "vmware",
    "vethernet",
    "wsl",
    "hyper-v",
    "docker",
    "tap-",
    "tun",
    "tailscale",
    "zerotier",
    "loopback",
    "npcap",
    "vpn",
    "wireguard",
)


def get_candidate_lan_ips() -> list[dict[str, str]]:
    """Returns candidate physical LAN IPv4 addresses (default-route IP first, excluding virtual adapters)."""
    physical_entries: list[dict[str, str]] = []
    virtual_entries: list[dict[str, str]] = []
    ip_to_iface: dict[str, str] = {}

    try:
        stats = psutil.net_if_stats()
        for iface_name, addrs in psutil.net_if_addrs().items():
            st = stats.get(iface_name)
            if st is not None and not st.isup:
                continue
            lower_name = iface_name.lower()
            is_virtual = any(k in lower_name for k in VIRTUAL_ADAPTER_KEYWORDS)
            for snic in addrs:
                if snic.family == socket.AF_INET:
                    ip = snic.address
                    if ip.startswith(("127.", "169.254.", "192.168.137.")):
                        continue
                    ip_to_iface[ip] = iface_name
                    item = {"ip": ip, "iface": iface_name}
                    if is_virtual:
                        virtual_entries.append(item)
                    else:
                        physical_entries.append(item)
    except Exception as exc:
        logger.debug("psutil interface scan warning: %s", exc)

    default_route_ip: str | None = None
    for target in ("8.8.8.8", "1.1.1.1", "192.168.1.1", "10.0.0.1"):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.settimeout(0.3)
                s.connect((target, 80))
                probe_ip = s.getsockname()[0]
                if not probe_ip.startswith(("127.", "169.254.", "192.168.137.")):
                    default_route_ip = probe_ip
                    break
            except OSError:
                continue

    virtual_ip_set = {e["ip"] for e in virtual_entries}
    ordered: list[dict[str, str]] = []
    seen_ips: set[str] = set()

    if default_route_ip and default_route_ip not in virtual_ip_set:
        ordered.append({"ip": default_route_ip, "iface": ip_to_iface.get(default_route_ip, "LAN")})
        seen_ips.add(default_route_ip)

    for entry in sorted(physical_entries, key=lambda x: x["ip"]):
        if entry["ip"] not in seen_ips:
            ordered.append(entry)
            seen_ips.add(entry["ip"])

    if not ordered:
        if default_route_ip and default_route_ip not in seen_ips:
            ordered.append({"ip": default_route_ip, "iface": ip_to_iface.get(default_route_ip, "LAN")})
            seen_ips.add(default_route_ip)
        for entry in sorted(virtual_entries, key=lambda x: x["ip"]):
            if entry["ip"] not in seen_ips:
                ordered.append(entry)
                seen_ips.add(entry["ip"])

    if not ordered:
        ordered.append({"ip": "127.0.0.1", "iface": "Loopback"})

    return ordered


def select_local_ip(preferred_ip: str = "") -> str:
    """Selects preferred_ip if present among active adapters, otherwise the top physical route IP."""
    candidates = get_candidate_lan_ips()
    pref = preferred_ip.strip()
    if pref and any(c["ip"] == pref for c in candidates):
        return pref
    return candidates[0]["ip"]


def find_and_bind_free_port(
    start: int = PORT_RANGE_START,
    attempts: int = PORT_RANGE_END - PORT_RANGE_START + 1,
) -> tuple[int, socket.socket]:
    """Binds and listens on the first free TCP port in [start, start + attempts - 1]."""
    for candidate in range(start, start + attempts):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("0.0.0.0", candidate))
            probe.listen(128)
            return candidate, probe
        except OSError:
            probe.close()
            continue
    raise RuntimeError(f"No free TCP port available in range {start}-{start + attempts - 1}")


def generate_qr_data_uri(data: str) -> str:
    """Generates a PNG QR code Data URI in memory using qrcode + Pillow."""
    if not data:
        return ""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    pil_img = img.get_image() if hasattr(img, "get_image") else img.convert("RGB")
    buffer = io.BytesIO()
    pil_img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _peer_host(request_or_ws: Any) -> str:
    client = getattr(request_or_ws, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return str(host).strip() if host else "127.0.0.1"


def _is_loopback_host(host: str) -> bool:
    h = host.strip().lower()
    if h in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _get_cf_connecting_ip(request_or_ws: Any) -> str | None:
    headers = getattr(request_or_ws, "headers", None)
    if not headers:
        return None
    val = headers.get("cf-connecting-ip")
    if val is not None:
        return str(val)
    if isinstance(headers, dict):
        for k, v in headers.items():
            if str(k).lower() == "cf-connecting-ip" and v is not None:
                return str(v)
    return None


def is_via_tunnel(request_or_ws: Any) -> bool:
    cf_ip = _get_cf_connecting_ip(request_or_ws)
    if cf_ip is None:
        return False
    return _is_loopback_host(_peer_host(request_or_ws))


def extract_client_ip(request_or_ws: Any) -> str:
    if is_via_tunnel(request_or_ws):
        raw_cf = (_get_cf_connecting_ip(request_or_ws) or "").strip()
        try:
            return str(ipaddress.ip_address(raw_cf))
        except ValueError:
            return "0.0.0.0"
    return _peer_host(request_or_ws)


def is_local_private_client(request_or_ws: Any) -> bool:
    if is_via_tunnel(request_or_ws):
        return False
    ip_str = extract_client_ip(request_or_ws)
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return ip_str == "localhost"


class NetworkWatcher:
    """Polls LAN IP changes every 5 seconds and emits network_changed when the active IP changes."""

    def __init__(
        self,
        get_preferred_ip: Callable[[], str],
        on_ip_changed: Callable[[str, list[dict[str, str]]], None],
    ) -> None:
        self._get_preferred_ip = get_preferred_ip
        self._on_ip_changed = on_ip_changed
        self.current_ip: str = select_local_ip(self._get_preferred_ip())
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    def refresh_now(self) -> tuple[str, list[dict[str, str]]]:
        candidates = get_candidate_lan_ips()
        pref = self._get_preferred_ip().strip()
        new_ip = pref if pref and any(c["ip"] == pref for c in candidates) else candidates[0]["ip"]
        changed = new_ip != self.current_ip
        self.current_ip = new_ip
        if changed:
            self._on_ip_changed(new_ip, candidates)
        return new_ip, candidates

    def start(self) -> None:
        self._stopped = False
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopped = True
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while not self._stopped:
            try:
                await asyncio.sleep(5.0)
                await asyncio.to_thread(self.refresh_now)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("NetworkWatcher iteration error: %s", exc)
