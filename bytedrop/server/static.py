"""Static asset serving and icon generation."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw

from bytedrop.app import ByteDropApplication
from bytedrop.auth import ByteDropHttpError
from bytedrop.config import ACCENT_PALETTES
from bytedrop.paths import get_ui_dir

logger = logging.getLogger("bytedrop.server.static")


def ensure_pwa_icons(icons_dir: Path) -> None:
    """Generates 192x192, 512x512, and 180x180 PNG icons and icon.svg into ui/web/icons/."""
    icons_dir.mkdir(parents=True, exist_ok=True)
    svg_path = icons_dir / "icon.svg"
    if not svg_path.exists():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0%" stop-color="#1d4ed8"/><stop offset="100%" stop-color="#3b82f6"/>'
            "</linearGradient></defs>"
            '<rect width="128" height="128" rx="28" fill="url(#g)"/>'
            '<path d="M64 26v52M42 56l22-22 22 22M34 92h60" stroke="#fff" stroke-width="10" '
            'stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
            "</svg>"
        )
        svg_path.write_text(svg, encoding="utf-8")

    targets = [
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("apple-touch-icon.png", 180),
    ]
    for filename, size in targets:
        out_path = icons_dir / filename
        if out_path.exists():
            continue
        try:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            radius = max(16, size // 5)
            draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=(29, 78, 216, 255))
            cx = size // 2
            top_y = int(size * 0.22)
            mid_y = int(size * 0.44)
            bot_y = int(size * 0.66)
            wing = int(size * 0.18)
            stem = max(4, int(size * 0.09))
            draw.polygon(
                [
                    (cx, top_y),
                    (cx - wing, mid_y),
                    (cx - stem, mid_y),
                    (cx - stem, bot_y),
                    (cx + stem, bot_y),
                    (cx + stem, mid_y),
                    (cx + wing, mid_y),
                ],
                fill=(255, 255, 255, 255),
            )
            bar_y = int(size * 0.74)
            bar_h = max(4, int(size * 0.07))
            draw.rectangle((cx - wing, bar_y, cx + wing, bar_y + bar_h), fill=(147, 197, 253, 255))
            img.save(out_path, format="PNG")
        except Exception as exc:
            logger.warning("Failed to generate PWA icon %s: %s", filename, exc)


def compute_asset_version(ui_dir: Path) -> str:
    hasher = hashlib.sha256()
    for rel in (
        "shared/format.js",
        "web/index.html",
        "web/app.css",
        "web/app.js",
        "web/i18n.js",
        "desktop/index.html",
        "desktop/desktop.css",
        "desktop/desktop.js",
        "desktop/i18n.js",
    ):
        p = ui_dir / rel
        if p.exists():
            with contextlib.suppress(OSError):
                hasher.update(p.read_bytes())
    return hasher.hexdigest()[:10] or "100"


def inject_theme_into_html(
    ctx: ByteDropApplication,
    raw_html: str,
    asset_version: str,
    is_desktop: bool = False,
) -> str:
    """Injects initial theme, accent CSS vars (desktop only), and safe boot config into HTML."""
    classes = []
    if is_desktop:
        if ctx.config.theme == "light":
            classes.append("light-mode")
        if ctx.config.language == "ar":
            classes.append("rtl-mode")
    body_class = f' class="{" ".join(classes)}"' if classes else ""

    accent_key = ctx.config.accent if is_desktop else "blue"
    p = ACCENT_PALETTES.get(accent_key, ACCENT_PALETTES["blue"])
    accent_vars = (
        f"--accent-from: {p['from']}; "
        f"--accent-to: {p['to']}; "
        f"--accent-light: {p['light']}; "
        f"--accent-rgb: {p['rgb']}; "
        f"--accent-dark-rgb: {p['darkRgb']};"
    )

    boot_data = ctx.config.public_subset(include_desktop_fields=is_desktop)
    boot_data["version"] = ctx.VERSION
    if not is_desktop:
        boot_data["app_appearance"] = ctx.appearance_dict()
    if is_desktop:
        boot_data["local_url"] = ctx.local_url
        boot_data["local_qr"] = ctx.local_qr

    config_json = json.dumps(boot_data)
    boot_style = f'<style id="bytedrop-boot-theme">:root {{ {accent_vars} }}</style>'
    boot_script = f"<script>window.__BYTEDROP_CONFIG__ = {config_json};</script>"

    version_clean = str(ctx.VERSION).lstrip("vV") or "1.0.0"
    html = raw_html.replace("{{INITIAL_BODY_CLASS}}", body_class)
    html = html.replace("{{ASSET_VERSION}}", asset_version)
    html = html.replace("v{{VERSION}}", f"v{version_clean}")
    html = html.replace("{{VERSION}}", f"v{version_clean}")
    if is_desktop and ctx.config.language == "ar":
        html = html.replace('<html lang="en"', '<html lang="ar" dir="rtl"', 1)
    if "</head>" in html:
        html = html.replace("</head>", f"    {boot_style}\n    {boot_script}\n</head>", 1)
    return html


def register_static_routes(app: FastAPI, ctx: ByteDropApplication) -> str:
    ui_dir = get_ui_dir()
    web_dir = ui_dir / "web"
    shared_dir = ui_dir / "shared"
    desktop_dir = ui_dir / "desktop"
    icons_dir = web_dir / "icons"

    web_dir.mkdir(parents=True, exist_ok=True)
    shared_dir.mkdir(parents=True, exist_ok=True)
    desktop_dir.mkdir(parents=True, exist_ok=True)
    ensure_pwa_icons(icons_dir)

    asset_version = compute_asset_version(ui_dir)

    app.mount("/static/shared", StaticFiles(directory=str(shared_dir)), name="static_shared")
    app.mount("/static/desktop", StaticFiles(directory=str(desktop_dir)), name="static_desktop")
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static_web")

    @app.get("/")
    async def serve_web_index() -> HTMLResponse:
        index_path = web_dir / "index.html"
        if not index_path.exists():
            raise ByteDropHttpError(500, "ui/web/index.html is missing", "MISSING_INDEX")
        raw_html = await asyncio.to_thread(index_path.read_text, encoding="utf-8")
        injected = inject_theme_into_html(ctx, raw_html, asset_version, is_desktop=False)
        return HTMLResponse(content=injected, headers={"Cache-Control": "no-cache"})

    return asset_version
