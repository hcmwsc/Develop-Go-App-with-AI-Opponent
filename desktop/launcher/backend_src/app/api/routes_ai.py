"""AI routes: legal moves with winrates, full position analysis, engine status."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..models.schemas import LegalMovesResponse, AnalysisResponse, EngineStatus
from ..services.game_service import get_game_service
from ..ai.manager import get_engine, current_engine_name, VALID_DIFFICULTIES
from ..ai.katago import KataGoEngine

router = APIRouter(prefix="/api", tags=["ai"])


@router.get("/legal_moves/{game_id}", response_model=LegalMovesResponse)
def legal_moves(game_id: str):
    svc = get_game_service()
    session = svc.get(game_id)
    if session is None:
        raise HTTPException(status_code=404, detail="game not found")
    color = session.board.to_move()
    moves = session.board.legal_moves(color)
    # Only attach candidate winrates if it's the human's turn
    resp = svc.legal_moves(game_id)
    return LegalMovesResponse(
        game_id=game_id,
        to_move=resp.to_move,
        moves=[[x, y] for x, y in moves],
        candidates=resp.candidates,
    )


@router.get("/analyze/{game_id}", response_model=AnalysisResponse)
def analyze(game_id: str, top_k: int = 15):
    svc = get_game_service()
    resp = svc.analyze(game_id)
    if not resp.ok:
        raise HTTPException(status_code=404, detail=resp.illegal_reason or "unknown")
    best = None
    # Pick the highest-winrate candidate as best_move
    if resp.candidates:
        best_c = max(resp.candidates, key=lambda c: c.winrate)
        best = {"x": best_c.x, "y": best_c.y, "color": resp.to_move}
    return AnalysisResponse(
        game_id=game_id,
        best_move=best,
        # resp.winrate 是当前走子方视角（玩家视角），前端直接显示
        winrate=resp.winrate if resp.winrate is not None else 0.5,
        score_lead=resp.score_lead,
        candidates=resp.candidates[:top_k],
        engine=resp.engine if hasattr(resp, "engine") else current_engine_name(),
    )


@router.get("/engine", response_model=EngineStatus)
def engine_status():
    kg = KataGoEngine()
    return EngineStatus(
        engine=current_engine_name(),
        katago_available=kg.is_available(),
        mcts_simulations=settings.mcts_simulations,
        difficulties=list(VALID_DIFFICULTIES),
    )
