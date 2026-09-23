"""FastAPI application.

Binds to ``127.0.0.1`` unless ``HOST`` is set explicitly, and logs a loud
warning when it is. There is no cloud deployment here by design: if this is
ever exposed, put it behind an HTTPS reverse proxy (see SECURITY.md).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import admin, auth, cameras, dashboard, events, sensors
from .config import get_config
from .pipeline.ingest import IngestWorker
from .security.headers import SecurityHeadersMiddleware

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("torch")

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


def resolve_host() -> tuple[str, bool]:
    """``(host, is_exposed)``. Loopback unless HOST says otherwise."""
    host = os.environ.get("HOST", "").strip()
    if not host:
        return "127.0.0.1", False
    exposed = host not in ("127.0.0.1", "localhost", "::1")
    return host, exposed


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    db.configure(config.db_path)
    db.init_db()

    host, exposed = resolve_host()
    if exposed:
        log.warning(
            "=" * 78 + "\n"
            "  HOST=%s — the API is bound to a NETWORK interface, not loopback.\n"
            "  This prototype has no TLS of its own. Put it behind an HTTPS reverse\n"
            "  proxy before exposing it, and read SECURITY.md first.\n" + "=" * 78,
            host,
        )

    worker = IngestWorker(config)
    worker.start()
    app.state.worker = worker
    app.state.config = config
    try:
        yield
    finally:
        worker.stop()


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(
        title=str(config.get("app.name", "Torch Camera Fusion (Prototype)")),
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,      # no public schema browser on a security-sensitive app
        redoc_url=None,
        openapi_url=None,
    )

    _, exposed = resolve_host()
    app.add_middleware(SecurityHeadersMiddleware, https=exposed)
    app.add_middleware(
        CORSMiddleware,
        # Only the frontend's own origin. No wildcards.
        allow_origins=list(config.get("app.frontend_origins", []) or []),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
        max_age=600,
    )

    for module in (auth, cameras, events, sensors, dashboard, admin):
        app.include_router(module.router)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        worker = getattr(app.state, "worker", None)
        return {
            "status": "ok",
            "ingest_running": worker is not None,
            "feeds": sorted(worker.adapters) if worker else [],
        }

    # The built frontend, when present. The frames folder is NEVER mounted.
    if WEB_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str, request: Request):
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            candidate = (WEB_DIST / full_path).resolve()
            if full_path and candidate.is_file() and WEB_DIST in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app()
