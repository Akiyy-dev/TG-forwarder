"""FastAPI application factory."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.errors import register_exception_handlers
from app.api.routes import auth as auth_routes
from app.api.routes import media as media_routes
from app.api.routes import reviews as reviews_routes
from app.api.routes import users as users_routes
from app.context import AppContext


def create_api_app(ctx: AppContext) -> FastAPI:
    docs_url = "/api/docs" if ctx.settings.web_docs_enabled else None
    redoc_url = "/api/redoc" if ctx.settings.web_docs_enabled else None
    openapi_url = "/api/openapi.json" if ctx.settings.web_docs_enabled else None

    app = FastAPI(
        title="TG-forwarder API",
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.state.ctx = ctx
    register_exception_handlers(app)

    origins = ctx.settings.web_allowed_origins or ["http://localhost:5173", "http://127.0.0.1:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(auth_routes.router, prefix="/api/v1")
    app.include_router(users_routes.router, prefix="/api/v1")
    app.include_router(reviews_routes.router, prefix="/api/v1")
    app.include_router(media_routes.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "data": {
                "web_enabled": ctx.settings.web_enabled,
                "started_at": ctx.started_at.isoformat(),
            },
        }

    dist = Path("web/dist")
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app
