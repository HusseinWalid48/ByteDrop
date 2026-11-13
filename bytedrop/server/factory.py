"""FastAPI application factory and uvicorn runner on a pre-bound socket."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bytedrop.app import ByteDropApplication
from bytedrop.auth import ByteDropHttpError
from bytedrop.server.routes_http import register_http_routes
from bytedrop.server.routes_ws import register_ws_routes
from bytedrop.server.static import register_static_routes

WS_MAX_SIZE_BYTES = 16 * 1024 * 1024  # 16 MB for up to 2,000 file metadata items


def create_fastapi_app(ctx: ByteDropApplication) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await ctx.start_background_tasks()
        try:
            yield
        finally:
            await ctx.stop_background_tasks()

    app = FastAPI(title="ByteDrop", version=ctx.VERSION, lifespan=lifespan)

    # Explicit CORS policy: only same-origin requests are accepted.
    # No allow_origins wildcard — cross-origin browsers will be blocked by preflight.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Content-Range", "X-Token", "X-Device-Id"],
    )

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next: object) -> object:
        call_fn = call_next  # type: ignore[assignment]
        response = await call_fn(request)  # type: ignore[operator]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        is_inline_download = request.url.path.startswith("/api/download/") and (
            request.query_params.get("inline") not in (None, "", "0", "false")
            or request.query_params.get("stream") not in (None, "", "0", "false")
        )
        if is_inline_download:
            response.headers["Content-Security-Policy"] = "sandbox"
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "img-src 'self' data: blob:; "
                "media-src 'self' blob: data:; "
                "font-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; "
                "connect-src 'self' ws: wss:; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ByteDropHttpError)
    async def bytedrop_error_handler(request: Request, exc: ByteDropHttpError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code})

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": f"HTTP_{exc.status_code}"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid request parameters", "code": "VALIDATION_ERROR"},
        )

    asset_version = register_static_routes(app, ctx)
    register_http_routes(app, ctx, asset_version)
    register_ws_routes(app, ctx)
    return app


def run_uvicorn(ctx: ByteDropApplication) -> None:
    fastapi_app = create_fastapi_app(ctx)
    config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=ctx.port,
        log_level="error",
        log_config=None,
        ws_max_size=WS_MAX_SIZE_BYTES,
    )
    server = uvicorn.Server(config)
    ctx.uvicorn_server = server
    if ctx.bound_socket is not None:
        server.run(sockets=[ctx.bound_socket])
    else:
        server.run()
