"""MCTS smoke test: ensure it produces a legal move and runs quickly on 9x9."""
import time

from app.core.board import GoBoard, BLACK
from app.ai.mcts import MCTSEngine


def test_mcts_returns_legal_move_9x9():
    b = GoBoard(size=9)
    eng = MCTSEngine(simulations=30, seed=42)
    t0 = time.time()
    res = eng.analyze(b, BLACK, top_k=5)
    elapsed = time.time() - t0
    assert res.best_move is not None
    x, y = res.best_move
    assert 0 <= x < 9 and 0 <= y < 9
    assert 0.0 <= res.winrate <= 1.0
    assert elapsed < 10.0, f"MCTS too slow: {elapsed:.2f}s"
    assert res.engine == "mcts"


def test_mcts_candidates_have_winrates():
    b = GoBoard(size=9)
    eng = MCTSEngine(simulations=20, seed=1)
    res = eng.analyze(b, BLACK, top_k=5)
    assert len(res.candidates) >= 1
    for c in res.candidates:
        assert 0.0 <= c.winrate <= 1.0
