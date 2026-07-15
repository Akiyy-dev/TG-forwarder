"""FastAPI application factory."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.api.errors import register_exception_handlers
from app.api.routes import auth as auth_routes
from app.api.routes import channels as channels_routes
from app.api.routes import dashboard as dashboard_routes
from app.api.routes import media as media_routes
from app.api.routes import reviews as reviews_routes
from app.api.routes import rules as rules_routes
from app.api.routes import system as system_routes
from app.api.routes import users as users_routes
from app.context import AppContext

# Repo root: app/api/app.py -> parents[2] == project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SPAStaticFiles(StaticFiles):
    """Serve index.html for client-side routes (e.g. /reviews) on refresh."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            # Missing hashed assets / real files should stay 404.
            if path.startswith("assets/") or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)


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
    app.include_router(rules_routes.router, prefix="/api/v1")
    app.include_router(channels_routes.router, prefix="/api/v1")
    app.include_router(dashboard_routes.router, prefix="/api/v1")
    app.include_router(system_routes.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "data": {
                "web_enabled": ctx.settings.web_enabled,
                "started_at": ctx.started_at.isoformat(),
            },
        }

    dist = _PROJECT_ROOT / "web" / "dist"
    if not dist.is_dir():
        cwd_dist = Path("web/dist")
        if cwd_dist.is_dir():
            dist = cwd_dist.resolve()

    if dist.is_dir():
        # Mount last so /api/* routes take precedence; SPA fallback for client routes.
        app.mount(
            "/",
            SPAStaticFiles(directory=str(dist), html=True),
            name="frontend",
        )

    return app
