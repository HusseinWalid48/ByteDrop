"""REST HTTP routes for ByteDrop v1.0.0 (transfers, resumable upload, Range download, shares, history)."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import Response

from bytedrop.app import ByteDropApplication
from bytedrop.auth import ByteDropHttpError
from bytedrop.config import ACCENT_PALETTES
from bytedrop.fsutil import CATEGORY_EXTENSIONS
from bytedrop.net import extract_client_ip, is_local_private_client, is_via_tunnel
from bytedrop.transfers.upload import MAX_CHUNK_BYTES, parse_content_range_offset


def register_http_routes(app: FastAPI, ctx: ByteDropApplication, asset_version: str) -> None:
    def ensure_authorized_and_not_blocked(
        request: Request,
        token: str | None,
        device_id: str | None = None,
    ) -> str:
        client_ip = extract_client_ip(request)
        ctx.auth.verify(token, client_ip)
        if ctx.devices.is_blocked(device_id=device_id, ip=client_ip):
            raise ByteDropHttpError(403, "Blocked by the PC", "DEVICE_BLOCKED")
        return client_ip

    def resolve_http_actor(device_id: str | None) -> str:
        if not device_id or not str(device_id).strip():
            return "phone"
        cleaned = ctx.devices.sanitize_device_id(device_id)
        if cleaned.lower() == "pc":
            return "phone"
        return cleaned

    @app.get("/api/meta")
    async def get_meta() -> dict[str, Any]:
        return {
            "version": ctx.VERSION,
            "asset_version": asset_version,
            "palettes": ACCENT_PALETTES,
            "categories": CATEGORY_EXTENSIONS,
        }

    @app.get("/api/verify")
    async def verify_token_endpoint(
        request: Request,
        token: str = Query(...),
        device_id: str | None = Query(None),
    ) -> dict[str, str]:
        ensure_authorized_and_not_blocked(request, token, device_id)
        return {"status": "authenticated", "version": ctx.VERSION}

    @app.get("/api/status")
    async def get_status(
        request: Request,
        token: str = Query(...),
        device_id: str | None = Query(None),
    ) -> dict[str, Any]:
        ensure_authorized_and_not_blocked(request, token, device_id)
        return ctx.snapshot(is_desktop=False)

    @app.get("/api/history")
    async def get_history(request: Request, token: str = Query(...)) -> dict[str, Any]:
        ensure_authorized_and_not_blocked(request, token)
        rows = await asyncio.to_thread(ctx.history.list_recent, 50)
        return {"history": rows}

    @app.post("/api/history/clear")
    async def clear_history(request: Request, token: str = Query(...)) -> dict[str, str]:
        ensure_authorized_and_not_blocked(request, token)
        await asyncio.to_thread(ctx.history.clear)
        ctx.events.emit({"type": "history_cleared"})
        return {"status": "cleared"}

    # ---------------- Phone -> PC Transfer Request & Resumable Upload (Section 2.1) ----------------
    @app.post("/api/transfers")
    async def create_transfer_request(
        request: Request,
        token: str | None = Query(None),
        x_token: str | None = Header(None),
    ) -> dict[str, Any]:
        auth_token = token or x_token
        try:
            body = await request.json()
        except Exception:
            raise ByteDropHttpError(400, "Malformed JSON body", "INVALID_JSON")
        if not isinstance(body, dict):
            raise ByteDropHttpError(400, "JSON object expected", "INVALID_JSON")

        dev_id = ctx.devices.sanitize_device_id(body.get("device_id"))
        client_ip = ensure_authorized_and_not_blocked(request, auth_token, dev_id)
        dev = ctx.devices.get_device(dev_id)
        dev_name = str(body.get("device_name") or (dev.name if dev else f"Phone ({client_ip})"))
        auto_accept = bool(ctx.config.auto_accept_local and is_local_private_client(request))
        via_str = "Cloud" if is_via_tunnel(request) else "Wi-Fi"

        evt = await asyncio.to_thread(
            ctx.transfers.create_incoming_request,
            dev_id,
            dev_name,
            body.get("files"),
            body.get("request_id"),
            auto_accept,
            via_str,
        )
        return evt

    @app.post("/api/transfers/cancel_all")
    async def cancel_all_transfers_endpoint(
        request: Request,
        token: str | None = Query(None),
        x_token: str | None = Header(None),
        device_id: str | None = Query(None),
    ) -> dict[str, Any]:
        ensure_authorized_and_not_blocked(request, token or x_token, device_id)
        actor = resolve_http_actor(device_id)
        res = await asyncio.to_thread(
            ctx.transfers.cancel_all_transfers,
            actor,
            actor,
        )
        return {"status": "cancelled_all", **res}

    @app.get("/api/upload/{transfer_id}")
    async def get_upload_offset(
        transfer_id: str,
        request: Request,
        token: str | None = Query(None),
        x_token: str | None = Header(None),
        device_id: str | None = Query(None),
    ) -> dict[str, Any]:
        ensure_authorized_and_not_blocked(request, token or x_token, device_id)
        offset = await asyncio.to_thread(ctx.upload_handler.get_committed_offset, transfer_id)
        return {"transfer_id": transfer_id, "offset": offset}

    @app.put("/api/upload/{transfer_id}")
    async def put_upload_chunk(
        transfer_id: str,
        request: Request,
        token: str | None = Query(None),
        x_token: str | None = Header(None),
        content_range: str | None = Header(None),
        x_chunk_offset: int | None = Header(None),
        x_device_id: str | None = Header(None),
    ) -> Any:
        ensure_authorized_and_not_blocked(request, token or x_token, x_device_id)
        offset = parse_content_range_offset(content_range, x_chunk_offset)

        buffer = bytearray()
        async for piece in request.stream():
            buffer.extend(piece)
            if len(buffer) > MAX_CHUNK_BYTES:
                raise ByteDropHttpError(413, "Chunk exceeds maximum size limit", "CHUNK_TOO_LARGE")

        chunk_bytes = bytes(buffer)
        buffer.clear()
        return await asyncio.to_thread(
            ctx.upload_handler.process_chunk,
            transfer_id,
            offset,
            chunk_bytes,
        )

    @app.delete("/api/upload/{transfer_id}")
    async def cancel_upload_endpoint(
        transfer_id: str,
        request: Request,
        token: str | None = Query(None),
        x_token: str | None = Header(None),
        device_id: str | None = Query(None),
    ) -> dict[str, Any]:
        ensure_authorized_and_not_blocked(request, token or x_token, device_id)
        actor = resolve_http_actor(device_id)
        dto = await asyncio.to_thread(ctx.transfers.cancel_transfer, transfer_id, actor, actor)
        if dto is None:
            raise ByteDropHttpError(404, "Active transfer not found", "TRANSFER_NOT_FOUND")
        return {"status": "cancelled", "transfer": dto}

    # ---------------- PC -> Phone Shares & Range Downloads (Section 2.1) ----------------
    @app.get("/api/shared")
    async def get_shared_files(
        request: Request,
        token: str = Query(...),
        device_id: str | None = Query(None),
    ) -> dict[str, Any]:
        ensure_authorized_and_not_blocked(request, token, device_id)
        return {"files": ctx.transfers.list_shares()}

    @app.delete("/api/shared/{share_id}")
    async def delete_shared_file(
        share_id: str,
        request: Request,
        token: str = Query(...),
        device_id: str | None = Query(None),
    ) -> dict[str, str]:
        ensure_authorized_and_not_blocked(request, token, device_id)
        actor = resolve_http_actor(device_id)
        removed = await asyncio.to_thread(ctx.transfers.remove_share, share_id, actor)
        if not removed:
            raise ByteDropHttpError(404, "Shared file not found", "SHARE_NOT_FOUND")
        return {"status": "removed"}

    @app.get("/api/download/{share_id}")
    async def download_share_endpoint(
        share_id: str,
        request: Request,
        token: str = Query(...),
        device_id: str = Query("phone"),
        inline: int = Query(0),
        stream: int = Query(0),
    ) -> Response:
        ensure_authorized_and_not_blocked(request, token, device_id)
        via_str = "Cloud" if is_via_tunnel(request) else "Wi-Fi"
        return await ctx.download_handler.serve_share(
            share_id=share_id,
            request=request,
            device_id=device_id,
            inline=bool(inline or stream),
            via=via_str,
        )
