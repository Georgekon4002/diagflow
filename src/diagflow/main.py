"""
DiagFlow — FastAPI Application Entry Point

Serves:
- REST API at /api/*
- Secretariat review dashboard at /
- OpenAPI docs at /docs
"""

from contextlib import asynccontextmanager
from pathlib import Path
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import structlog

from diagflow import __app_name__, __version__
from diagflow.config import settings
from diagflow.api.routes import router as api_router
from diagflow.utils.logging import setup_logging

setup_logging(settings.log_level)
logger = structlog.get_logger(__name__)

# Hold a strong reference to background startup task so it is never GC'd mid-flight
_startup_sync_task: asyncio.Task | None = None


# ── Global SLIS DB Connection Status ──
SLIS_STATUS: dict[str, str | None] = {
    "status": "mock" if settings.use_mock_slis_db else "unknown",
    "error": None,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — runs setup on startup and cleanup on shutdown."""
    global _startup_sync_task
    # ── Ensure admin users table exists & seed default accounts once if empty ──
    import diagflow.db.diagflow_db as cfg_db
    try:
        await asyncio.to_thread(cfg_db.ensure_admin_users_initialized)
    except Exception as exc:
        logger.warning("ensure_admin_users_failed", error=str(exc))

    # ── Sync Doctors and Pull Exams in background on startup ──
    from diagflow.services.slis_sync import pull_from_slis, sync_doctors, cleanup_mock_data

    async def _async_startup_sync():
        def _do_sync():
            if settings.use_mock_slis_db:
                SLIS_STATUS["status"] = "mock"
                SLIS_STATUS["error"] = None
                try:
                    doc_res = sync_doctors()
                    logger.info("startup_doctor_sync", synced=doc_res.get("synced", 0))
                    result = pull_from_slis()
                    logger.info(
                        "startup_slis_pull",
                        pulled=result.get("pulled", 0),
                        expired=result.get("expired", 0),
                        total_pending=result.get("total_pending", 0),
                    )
                except Exception as exc:
                    logger.warning("mock_slis_startup_warning", error=str(exc))
            else:
                # Production: test real Slis DB connection using pooled engine
                try:
                    from sqlalchemy import text
                    from diagflow.db.engines import get_slis_engine
                    engine = get_slis_engine()
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1"))

                    SLIS_STATUS["status"] = "connected"
                    SLIS_STATUS["error"] = None
                    logger.info("slis_db_connected_successfully")

                    # Purge any local mock databases and clear in-memory caches
                    cleanup_mock_data()

                    doc_res = sync_doctors()
                    logger.info("startup_doctor_sync", synced=doc_res.get("synced", 0))
                    result = pull_from_slis()
                    logger.info(
                        "startup_slis_pull",
                        pulled=result.get("pulled", 0),
                        expired=result.get("expired", 0),
                        total_pending=result.get("total_pending", 0),
                    )
                except Exception as exc:
                    SLIS_STATUS["status"] = "error"
                    SLIS_STATUS["error"] = str(exc)
                    logger.error("slis_db_connection_failed", error=str(exc))

        await asyncio.to_thread(_do_sync)

    _startup_sync_task = asyncio.create_task(_async_startup_sync())

    # ── Start APScheduler for daily background sync (non-blocking async job) ──
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()

    async def daily_sync():
        logger.info("running_daily_background_sync")
        if settings.use_mock_slis_db or SLIS_STATUS["status"] == "connected":
            try:
                await asyncio.to_thread(sync_doctors)
            except Exception as e:
                logger.error("daily_sync_error", error=str(e))

    scheduler.add_job(daily_sync, 'cron', hour=3, minute=0)
    scheduler.start()
    logger.info("apscheduler_started")

    yield

    # Cleanup
    if _startup_sync_task and not _startup_sync_task.done():
        _startup_sync_task.cancel()
    scheduler.shutdown(wait=False)

    from diagflow.db.engines import dispose_engines
    dispose_engines()


_is_prod = settings.app_env.lower() == "production"

app = FastAPI(
    title=__app_name__,
    version=__version__,
    description="Automated CT/MRI report assignment engine for Kosmoiatriki",
    lifespan=lifespan,
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

# ── CORS (explicit configured origins, no wildcard + credentials reflection) ──
_allowed_origins = [
    o.strip() for o in (settings.cors_origins or "").split(",") if o.strip() and o.strip() != "*"
] or [
    f"http://localhost:{settings.app_port}",
    f"http://127.0.0.1:{settings.app_port}",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Token", "Authorization"],
)

# ── Health check (must be registered before the catch-all static mount) ──
@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": __app_name__,
        "version": __version__,
        "environment": settings.app_env,
    }

# ── API routes ──
app.include_router(api_router, prefix="/api")

# ── Serve the frontend dashboard as static files ──
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

