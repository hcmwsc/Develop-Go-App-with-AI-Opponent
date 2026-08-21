"""Pydantic request/response schemas."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class NewGameRequest(BaseModel):
    board_size: int = Field(19, ge=2, le=25)
    komi: float = 7.5
    player_color: str = "black"  # human's color: black | white
    ai_engine: Optional[str] = None  # "auto" | "mcts" | "katago"
    ai_difficulty: str = "medium"  # beginner | easy | medium | hard


class MoveInfo(BaseModel):
    x: int
    y: int
    color: str  # "black" | "white"


class PlayRequest(BaseModel):
    game_id: str
    x: Optional[int] = None
    y: Optional[int] = None
    pass_move: bool = False
    resign: bool = False


class CandidateMove(BaseModel):
    x: int
    y: int
    winrate: float
    visits: int = 0
    score_lead: Optional[float] = None
    prior: Optional[float] = None


class PlayResponse(BaseModel):
    game_id: str
    ok: bool
    illegal_reason: Optional[str] = None
    board: list[list[int]]
    to_move: str  # "black" | "white"
    captures: dict[str, int]
    last_move: Optional[MoveInfo] = None
    ai_move: Optional[MoveInfo] = None
    # winrate: 当前走子方 (to_move) 视角的胜率，用于前端统一显示
    winrate: Optional[float] = None
    # ai_winrate: 仅在 AI 相关响应中有效，表示 AI 方视角的胜率
    # - AI 走子时：AI 自己的胜率（用于认输判断）
    # - 其他场景：None
    ai_winrate: Optional[float] = None
    # score_lead: 与 winrate 视角一致（当前走子方领先多少目，正=领先）
    score_lead: Optional[float] = None
    candidates: list[CandidateMove] = []
    finished: bool = False
    ai_resigned: bool = False  # AI 主动认输
    ai_pending: bool = False  # AI 应手待处理（前端需调 ai_move 端点）
    score: Optional[dict] = None


class LegalMovesResponse(BaseModel):
    game_id: str
    to_move: str
    moves: list[list[int]]  # [[x, y], ...]
    candidates: list[CandidateMove] = []


class UndoResponse(BaseModel):
    game_id: str
    ok: bool
    board: list[list[int]]
    to_move: str
    captures: dict[str, int]


class GameState(BaseModel):
    game_id: str
    board: list[list[int]]
    board_size: int
    komi: float
    to_move: str
    captures: dict[str, int]
    move_log: list[Optional[MoveInfo]] = []
    finished: bool = False
    score: Optional[dict] = None
    difficulty: Optional[str] = None
    engine: Optional[str] = None


class AnalysisResponse(BaseModel):
    game_id: str
    best_move: Optional[MoveInfo] = None
    winrate: float
    score_lead: Optional[float] = None
    candidates: list[CandidateMove] = []
    engine: str


class EngineStatus(BaseModel):
    engine: str
    katago_available: bool
    mcts_simulations: int
    difficulties: list[str] = []


class ReviewCandidate(BaseModel):
    x: int
    y: int
    winrate: float
    visits: int = 0
    score_lead: Optional[float] = None
    prior: Optional[float] = None


class ReviewEntry(BaseModel):
    move_number: int
    move: Optional[list[int]] = None  # [x, y] or None for pass
    color: str  # "black" | "white"
    pre_winrate: Optional[float] = None
    post_winrate: Optional[float] = None
    pre_score_lead: Optional[float] = None
    post_score_lead: Optional[float] = None
    best_move: Optional[list[int]] = None  # AI 推荐的最佳应手
    candidates: list[ReviewCandidate] = []
    is_key_move: bool = False  # 关键转折点（胜率大幅变化）


class ReviewResponse(BaseModel):
    game_id: str
    board_size: int
    komi: float
    difficulty: str
    engine: str
    human_color: str
    ai_color: str
    initial_board: list[list[int]]
    move_log: list[Optional[list]] = []  # [x, y, color] or None for pass
    entries: list[ReviewEntry] = []
    finished: bool = False
    score: Optional[dict] = None
