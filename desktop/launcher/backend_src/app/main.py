"""FastAPI application entry point.

Run:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .api import routes_game, routes_ai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weiqi")

app = FastAPI(
    title="Weiqi (Go) AI Backend",
    version="0.1.0",
    description="Go rules engine + MCTS/KataGo AI for the Weiqi app.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    logger.info("CORS origins: %s", settings.cors_origins)
    logger.info("AI engine preference: %s", settings.ai_engine)
    logger.info("MCTS simulations: %d", settings.mcts_simulations)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


app.include_router(routes_game.router)
app.include_router(routes_ai.router)

# ---- Serve frontend static files (production mode) -----------------------
# In packaged mode, frontend/dist is placed alongside the backend app.
# We look for it in several candidate locations to support both dev and
# PyInstaller / Electron packaging layouts.
_STATIC_CANDIDATES = [
    Path(__file__).resolve().parent.parent.parent / "frontend" / "dist",  # dev: backend/../frontend/dist
    Path(__file__).resolve().parent.parent / "frontend" / "dist",          # bundled: backend/frontend/dist
    Path(__file__).resolve().parent / "static",                             # PyInstaller _MEIPASS/static
    Path(os.environ.get("WEIQI_STATIC_DIR", "")) / ".",                   # explicit override
]

_static_mounted = False
for _candidate in _STATIC_CANDIDATES:
    _idx = os.path.join(str(_candidate), "index.html")
    if _candidate.is_dir() and Path(_idx).exists():
        app.mount("/", StaticFiles(directory=str(_candidate), html=True), name="static")
        logger.info("Serving frontend static files from %s", _candidate)
        _static_mounted = True
        break

if not _static_mounted:
    logger.info("No frontend dist found — API-only mode")

    @app.get("/")
    def root() -> dict:
        return {
            "name": app.title,
            "version": app.version,
            "docs": "/docs",
            "endpoints": [
                "/api/new_game",
                "/api/play",
                "/api/undo",
                "/api/state/{game_id}",
                "/api/legal_moves/{game_id}",
                "/api/analyze/{game_id}",
                "/api/engine",
                "/api/sgf/{game_id}",
            ],
        }
