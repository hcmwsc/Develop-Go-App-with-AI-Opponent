"""AI engine manager: picks KataGo if available, else MCTS.

`create_engine(difficulty)` returns a fresh engine for a single game session,
so different games can run at different difficulties. `get_engine()` remains
as a default (medium difficulty) singleton for backward compatibility.
"""
from __future__ import annotations

import threading
from typing import Optional

from ..config import settings
from .base import AIEngine
from .mcts import MCTSEngine
from .katago import KataGoEngine


_engine: Optional[AIEngine] = None
_mcts: Optional[MCTSEngine] = None
_katago: Optional[KataGoEngine] = None
_lock = threading.Lock()

VALID_DIFFICULTIES = ("beginner", "easy", "medium", "hard")


def create_engine(difficulty: str = "medium") -> AIEngine:
    """Create a per-game AI engine.

    For MCTS, the difficulty maps to (simulations, rollout_depth, exploration).
    For KataGo, difficulty is acknowledged but KataGo's strength is mainly
    controlled by maxVisits in its config; we still create a fresh instance
    so the per-game difficulty is recorded.
    """
    if difficulty not in VALID_DIFFICULTIES:
        difficulty = "medium"
    choice = settings.ai_engine.lower()
    if choice == "katago":
        kg = KataGoEngine()
        if not kg.is_available():
            raise RuntimeError(
                "KataGo selected but not configured. Set KATAGO_BINARY, "
                "KATAGO_MODEL, KATAGO_CONFIG or use GO_AI_ENGINE=auto."
            )
        return kg
    if choice == "mcts":
        return MCTSEngine(difficulty=difficulty)
    # auto
    kg = KataGoEngine()
    if kg.is_available():
        return kg
    return MCTSEngine(difficulty=difficulty)


def get_engine() -> AIEngine:
    """Default singleton engine (medium difficulty). Prefer
    `create_engine(difficulty)` for per-game engines."""
    global _engine, _mcts, _katago
    with _lock:
        choice = settings.ai_engine.lower()
        if choice == "mcts":
            if _mcts is None:
                _mcts = MCTSEngine()
            return _mcts
        if choice == "katago":
            if _katago is None:
                _katago = KataGoEngine()
            if not _katago.is_available():
                raise RuntimeError(
                    "KataGo selected but not configured. Set KATAGO_BINARY, "
                    "KATAGO_MODEL, KATAGO_CONFIG or use GO_AI_ENGINE=auto."
                )
            return _katago
        # auto
        if _katago is None:
            _katago = KataGoEngine()
        if _katago.is_available():
            return _katago
        if _mcts is None:
            _mcts = MCTSEngine()
        return _mcts


def current_engine_name() -> str:
    return get_engine().name


def reset_engine() -> None:
    """Force re-evaluation (used after config changes)."""
    global _engine, _mcts, _katago
    with _lock:
        _engine = None
        _mcts = None
        if _katago is not None:
            _katago.shutdown()
        _katago = None
