"""FastAPI application entry point.

Run:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


app.include_router(routes_game.router)
app.include_router(routes_ai.router)
