"""Game lifecycle routes: new game, play, undo, state, SGF export."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.schemas import (
    NewGameRequest,
    PlayRequest,
    PlayResponse,
    UndoResponse,
    GameState,
    ReviewResponse,
)
from ..services.game_service import get_game_service

router = APIRouter(prefix="/api", tags=["game"])


@router.post("/new_game", response_model=GameState)
def new_game(req: NewGameRequest):
    svc = get_game_service()
    session = svc.new_game(
        board_size=req.board_size,
        komi=req.komi,
        human_color=req.player_color,
        difficulty=req.ai_difficulty,
    )
    return session.to_state()


@router.post("/play", response_model=PlayResponse)
def play(req: PlayRequest):
    svc = get_game_service()
    resp = svc.play_human(
        req.game_id, req.x, req.y, req.pass_move, req.resign
    )
    if not resp.ok and resp.illegal_reason == "game not found":
        raise HTTPException(status_code=404, detail=resp.illegal_reason)
    return resp


@router.post("/ai_move", response_model=PlayResponse)
def ai_move(game_id: str):
    """Ask the AI to move when it's the AI's turn (e.g. human is white)."""
    svc = get_game_service()
    resp = svc.ai_move(game_id)
    if not resp.ok and resp.illegal_reason == "game not found":
        raise HTTPException(status_code=404, detail=resp.illegal_reason)
    return resp


@router.post("/undo", response_model=UndoResponse)
def undo(game_id: str):
    svc = get_game_service()
    resp = svc.undo(game_id)
    if not resp.ok and resp.illegal_reason == "game not found":
        raise HTTPException(status_code=404, detail=resp.illegal_reason)
    return resp


@router.get("/state/{game_id}", response_model=GameState)
def state(game_id: str):
    svc = get_game_service()
    session = svc.get(game_id)
    if session is None:
        raise HTTPException(status_code=404, detail="game not found")
    return session.to_state()


@router.get("/sgf/{game_id}")
def sgf(game_id: str):
    svc = get_game_service()
    text = svc.export_sgf(game_id)
    if text is None:
        raise HTTPException(status_code=404, detail="game not found")
    return {"game_id": game_id, "sgf": text}


@router.get("/review/{game_id}", response_model=ReviewResponse)
def review(game_id: str):
    """复盘数据：每一步的胜率/目差/候选点，用于前端回放和分析。"""
    svc = get_game_service()
    data = svc.review(game_id)
    if data is None:
        raise HTTPException(status_code=404, detail="game not found")
    return data
