"""Abstract AI engine interface.

All engines return:
- best_move: (x, y) or None (pass/resign)
- winrate: float in [0, 1] from the perspective of the player to move
- candidates: list of MoveEvaluation for top candidate points
- score_lead: optional estimated point difference (positive = current player ahead)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from ..core.board import GoBoard, Color


@dataclass
class MoveEvaluation:
    x: int
    y: int
    winrate: float  # 0..1 from perspective of player to move
    visits: int = 0
    score_lead: Optional[float] = None
    prior: Optional[float] = None


@dataclass
class AnalysisResult:
    best_move: Optional[tuple[int, int]]
    winrate: float  # current player's win probability
    score_lead: Optional[float]
    candidates: list[MoveEvaluation] = field(default_factory=list)
    engine: str = "unknown"
    resign: bool = False


class AIEngine(ABC):
    """Base class for all AI engines."""

    name: str = "base"

    @abstractmethod
    def analyze(self, board: GoBoard, color: Color, top_k: int = 10) -> AnalysisResult:
        """Return best move and analysis for the given position."""
        raise NotImplementedError

    def best_move(self, board: GoBoard, color: Color) -> Optional[tuple[int, int]]:
        return self.analyze(board, color, top_k=1).best_move

    def is_available(self) -> bool:
        return True
