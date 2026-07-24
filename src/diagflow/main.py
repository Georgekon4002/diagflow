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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — runs setup on startup and cleanup on shutdown."""
    setup_logging(settings.log_level)

    # ── Pull from Slis on startup ──
    # Expires old synced rows and verifies the DB schema is current.
    # In production this would trigger the real Slis stored-procedure pull.
    from diagflow.services.slis_sync import pull_from_slis, sync_diagnosticians, sync_doctors
    result = pull_from_slis()
    logger.info(
        "startup_slis_pull",
        expired=result.get("expired", 0),
        total_pending=result.get("total_pending", 0),
    )

    # ── Start APScheduler for daily background sync ──
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    
    def daily_sync():
        logger.info("running_daily_background_sync")
        sync_doctors()

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

