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

from diagflow import __app_name__, __version__
from diagflow.config import settings
from diagflow.api.routes import router as api_router
from diagflow.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — runs setup on startup and cleanup on shutdown."""
    setup_logging(settings.log_level)

    # TODO: Initialize database engines when DB access is available
    # from diagflow.db.engines import init_engines
    # init_engines()

    yield

    # Cleanup
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

# ── API routes ──
app.include_router(api_router, prefix="/api")

# ── Serve the frontend dashboard as static files ──
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": __app_name__,
        "version": __version__,
        "environment": settings.app_env,
    }
