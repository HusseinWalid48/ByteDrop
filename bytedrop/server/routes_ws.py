"""WebSocket signalling route (/ws?token=...&device_id=...) with snapshot, monotonic seq events, and commands."""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from bytedrop.app import ByteDropApplication
from bytedrop.auth import ByteDropHttpError
from bytedrop.devices import WS_CLOSE_KICKED
from bytedrop.net import extract_client_ip, is_local_private_client, is_via_tunnel

logger = logging.getLogger("bytedrop.server.ws")


def register_ws_routes(app: FastAPI, ctx: ByteDropApplication) -> None:
    @app.websocket("/ws")
    async def websocket_endpoint(
        websocket: WebSocket,
        token: str = Query(...),
        device_id: str | None = Query(None),
        device_name: str | None = Query(None),
    ) -> None:
        client_ip = extract_client_ip(websocket)
        via_tunnel = is_via_tunnel(websocket)

        try:
            ctx.auth.verify(token, client_ip)
        except ByteDropHttpError:
            await websocket.accept()
            await websocket.close(code=1008, reason="Unauthorized")
            return

        clean_dev_id = ctx.devices.sanitize_device_id(device_id)
        if ctx.devices.is_blocked(device_id=clean_dev_id, ip=client_ip):
            await websocket.accept()
            await websocket.send_json({
                "type": "kicked",
                "code": "DEVICE_BLOCKED",
                "reason": "Blocked by the PC",
            })
            await websocket.close(code=WS_CLOSE_KICKED, reason="Blocked by the PC")
            return

        await websocket.accept()
        dev = await ctx.devices.register_socket(
            websocket=websocket,
            device_id=clean_dev_id,
            ip=client_ip,
            via_tunnel=via_tunnel,
            device_name=device_name,
        )

        # Send initial full snapshot on connect (Section 2.1)
        await websocket.send_json(ctx.snapshot(is_desktop=False))

        # Notify all UIs of updated device presence
        ctx.events.emit({
            "type": "devices_updated",
            "devices": ctx.devices.list_devices(),
            "blocked_devices": ctx.devices.list_blocked(),
            "connected_count": ctx.devices.active_device_count(),
        })

        bg_tasks: set[asyncio.Task[None]] = set()
        try:
            while True:
                data: dict[str, Any] = await websocket.receive_json()
                if not isinstance(data, dict):
                    continue

                msg_type = str(data.get("type") or "")
                current_dev_id = ctx.devices.get_device_id_for_ws(websocket) or dev.id

                if ctx.devices.is_blocked(device_id=current_dev_id, ip=client_ip):
                    await websocket.send_json({
                        "type": "kicked",
                        "code": "DEVICE_BLOCKED",
                        "reason": "Blocked by the PC",
                    })
                    await websocket.close(code=WS_CLOSE_KICKED, reason="Blocked by the PC")
                    return

                if msg_type == "hello":
                    new_id = ctx.devices.sanitize_device_id(str(data.get("device_id") or current_dev_id))
                    if ctx.devices.is_blocked(device_id=new_id, ip=client_ip):
                        await websocket.send_json({
                            "type": "kicked",
                            "code": "DEVICE_BLOCKED",
                            "reason": "Blocked by the PC",
                        })
                        await websocket.close(code=WS_CLOSE_KICKED, reason="Blocked by the PC")
                        return
                    dev = await ctx.devices.register_socket(
                        websocket=websocket,
                        device_id=new_id,
                        ip=client_ip,
                        via_tunnel=via_tunnel,
                        device_name=str(data.get("device_name") or dev.name),
                    )
                    ctx.events.emit({
                        "type": "devices_updated",
                        "devices": ctx.devices.list_devices(),
                        "blocked_devices": ctx.devices.list_blocked(),
                        "connected_count": ctx.devices.active_device_count(),
                    })

                elif msg_type == "get_snapshot":
                    await websocket.send_json(ctx.snapshot(is_desktop=False))

                elif msg_type in ("request_transfer", "transfer_request"):
                    req_id = str(data.get("request_id") or "")[:64] or None
                    try:
                        auto_accept = bool(ctx.config.auto_accept_local and is_local_private_client(websocket))
                        dev_via = "Cloud" if via_tunnel else "Wi-Fi"
                        await asyncio.to_thread(
                            ctx.transfers.create_incoming_request,
                            current_dev_id,
                            dev.name,
                            data.get("files"),
                            req_id,
                            auto_accept,
                            dev_via,
                        )
                    except ByteDropHttpError as b_err:
                        await websocket.send_json({
                            "type": "transfer_error",
                            "code": b_err.code,
                            "limit": ctx.config.max_request_files,
                            "request_id": req_id,
                            "detail": b_err.detail,
                        })

                elif msg_type in ("accept", "transfer_accepted"):
                    req_id = str(data.get("request_id") or "")[:64]
                    if req_id:
                        async def _run_accept(rid: str, dev_id: str) -> None:
                            try:
                                res = await asyncio.to_thread(ctx.transfers.accept_request, rid, dev_id)
                                if res is None:
                                    with suppress(Exception):
                                        await websocket.send_json({"type": "transfer_expired", "request_id": rid})
                            except Exception as exc:
                                logger.debug("accept_request task warning: %s", exc)

                        task = asyncio.create_task(_run_accept(req_id, current_dev_id))
                        bg_tasks.add(task)
                        task.add_done_callback(bg_tasks.discard)

                elif msg_type in ("reject", "transfer_rejected"):
                    req_id = str(data.get("request_id") or "")[:64]
                    if req_id:
                        await asyncio.to_thread(ctx.transfers.reject_request, req_id, current_dev_id)

                elif msg_type in ("pause", "transfer_pause"):
                    tid = str(data.get("transfer_id") or data.get("id") or data.get("share_id") or "")[:64]
                    if tid:
                        await asyncio.to_thread(ctx.transfers.pause_transfer, tid, current_dev_id)

                elif msg_type in ("resume", "transfer_resume"):
                    tid = str(data.get("transfer_id") or data.get("id") or data.get("share_id") or "")[:64]
                    if tid:
                        await asyncio.to_thread(ctx.transfers.resume_transfer, tid, current_dev_id)

                elif msg_type in ("cancel", "transfer_cancel", "cancel_prepare"):
                    tid = str(
                        data.get("transfer_id")
                        or data.get("id")
                        or data.get("share_id")
                        or data.get("request_id")
                        or ""
                    )[:64]
                    if tid:
                        await asyncio.to_thread(ctx.transfers.cancel_any, tid, current_dev_id, current_dev_id)

                elif msg_type in ("cancel_all", "transfers_cancel_all"):
                    await asyncio.to_thread(ctx.transfers.cancel_all_transfers, current_dev_id, current_dev_id)

                elif msg_type == "remove_share":
                    sid = str(data.get("share_id") or "")[:64]
                    if sid:
                        await asyncio.to_thread(ctx.transfers.remove_share, sid, current_dev_id)

                elif msg_type == "text_sync":
                    content = data.get("content", "")
                    # Guard against oversized payloads before they reach the clipboard manager
                    from bytedrop.clipboard import MAX_CLIPBOARD_CHARS
                    if isinstance(content, str) and len(content) <= MAX_CLIPBOARD_CHARS:
                        await asyncio.to_thread(ctx.clipboard.push_text, content, "mobile")

        except WebSocketDisconnect:
            logger.debug("WebSocket client disconnected: %s", dev.id)
        except Exception as exc:
            logger.debug("WebSocket connection ended: %s", exc)
        finally:
            ctx.devices.unregister_socket(websocket)
            ctx.events.emit({
                "type": "devices_updated",
                "devices": ctx.devices.list_devices(),
                "blocked_devices": ctx.devices.list_blocked(),
                "connected_count": ctx.devices.active_device_count(),
            })
