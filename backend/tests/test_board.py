"""Rules engine tests: legality, captures, ko, suicide, scoring."""
import pytest

from app.core.board import GoBoard, BLACK, WHITE, EMPTY
from app.core.scoring import score_chinese


def test_place_and_capture():
    b = GoBoard(size=9)
    # White group with one liberty at (0,1); black plays there to capture
    b.place_stone(0, 0, WHITE)
    b.place_stone(1, 0, BLACK)
    res = b.place_stone(0, 1, BLACK)
    assert res["ok"]
    assert (0, 0) in res["captured"]
    assert b.get(0, 0) == EMPTY
    assert b.captures[BLACK] == 1


def test_suicide_forbidden():
    b = GoBoard(size=9)
    # White surrounds (0,0) except the corner itself
    b.place_stone(1, 0, WHITE)
    b.place_stone(0, 1, WHITE)
    # Black playing (0,0) would have no liberties => suicide
    assert not b.is_legal(0, 0, BLACK)


def test_ko_simple():
    # Minimal ko shape. White stone at (1,1) has one liberty at (2,1).
    # Black plays (2,1), captures white (1,1). Black (2,1) ends up with one
    # liberty (the captured spot), so white cannot immediately recapture.
    #
    #   x=0   1     2     3
    # y=0  .   B     W     .
    # y=1  B   W   (cap)  W
    # y=2  .   B     W     .
    b = GoBoard(size=5)
    b.grid[0][1] = BLACK  # (1,0)
    b.grid[1][0] = BLACK  # (0,1)
    b.grid[1][1] = WHITE  # (1,1) - stone to be captured
    b.grid[2][1] = BLACK  # (1,2)
    b.grid[0][2] = WHITE  # (2,0)
    b.grid[1][3] = WHITE  # (3,1)
    b.grid[2][2] = WHITE  # (2,2)
    b.history = [b._hash_position()]
    res = b.place_stone(2, 1, BLACK)
    assert res["ok"], f"capture should be legal: {res}"
    assert (1, 1) in res["captured"]
    assert b.ko_point == (1, 1), f"ko_point should be set, got {b.ko_point}"
    # White cannot immediately recapture at (1,1) (ko)
    assert not b.is_legal(1, 1, WHITE), "ko recapture should be illegal"


def test_legal_moves_count():
    b = GoBoard(size=9)
    moves = b.legal_moves(BLACK)
    assert len(moves) == 81  # empty board, all points legal


def test_scoring_simple():
    b = GoBoard(size=5)
    # Black fills entire top row, white fills bottom row
    for x in range(5):
        b.place_stone(x, 0, BLACK)
    for x in range(5):
        b.place_stone(x, 4, WHITE)
    # Need to alternate turns in real game; for scoring test just score
    sc = score_chinese(b, komi=0.0)
    assert sc.black >= 5
    assert sc.white >= 5


def test_to_move_alternates():
    b = GoBoard(size=9)
    assert b.to_move() == BLACK
    b.place_stone(0, 0, BLACK)
    assert b.to_move() == WHITE
    b.place_stone(1, 0, WHITE)
    assert b.to_move() == BLACK


def test_two_passes_end_game():
    b = GoBoard(size=9)
    b.pass_move(BLACK)
    b.pass_move(WHITE)
    assert b.is_finished()


def test_board_clone_independent():
    b = GoBoard(size=9)
    b.place_stone(0, 0, BLACK)
    c = b.clone()
    c.place_stone(1, 0, WHITE)
    assert b.get(1, 0) == EMPTY
    assert c.get(1, 0) == WHITE
