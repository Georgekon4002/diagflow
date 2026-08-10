"""
DiagFlow — FastAPI Application Entry Point

Serves:
- REST API at /api/*
- Secretariat review dashboard at /
- OpenAPI docs at /docs
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import structlog

from diagflow import __app_name__, __version__
from diagflow.config import settings
from diagflow.api.routes import router as api_router
from diagflow.utils.logging import setup_logging

logger = structlog.get_logger(__name__)


# ── Global SLIS DB Connection Status ──
SLIS_STATUS: dict[str, str | None] = {
    "status": "mock" if settings.use_mock_slis_db else "unknown",
    "error": None,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — runs setup on startup and cleanup on shutdown."""
    # ── Ensure admin users table exists & seed accounts ──
    import diagflow.db.diagflow_db as cfg_db
    try:
        cfg_db.get_all_admin_users()
    except Exception as exc:
        logger.warning("ensure_admin_users_failed", error=str(exc))

    # ── Sync Doctors and Pull Exams in background on startup ──
    from diagflow.services.slis_sync import pull_from_slis, sync_doctors
    import asyncio

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
                # Production: test real Slis DB connection
                try:
                    from sqlalchemy import create_engine, text
                    engine = create_engine(settings.slis_db_connection_string, connect_args={"timeout": 10})
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1"))
                    
                    SLIS_STATUS["status"] = "connected"
                    SLIS_STATUS["error"] = None
                    logger.info("slis_db_connected_successfully")

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

    asyncio.create_task(_async_startup_sync())

    # ── Start APScheduler for daily background sync ──
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    
    def daily_sync():
        logger.info("running_daily_background_sync")
        if settings.use_mock_slis_db or SLIS_STATUS["status"] == "connected":
            try:
                sync_doctors()
            except Exception as e:
                logger.error("daily_sync_error", error=str(e))

    scheduler.add_job(daily_sync, 'cron', hour=3, minute=0)
    scheduler.start()
    logger.info("apscheduler_started")

    # TODO: Initialize database engines when real MSSQL DB access is available
    # from diagflow.db.engines import init_engines
    # init_engines()

    yield

    # Cleanup
    scheduler.shutdown()
    
    # TODO: Dispose database engines
    # from diagflow.db.engines import dispose_engines
    # dispose_engines()


app = FastAPI(
    title=__app_name__,
    version=__version__,
    description="Automated CT/MRI report assignment engine for Kosmoiatriki",
    lifespan=lifespan,
)

# ── CORS (allow the dashboard and development tools) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

