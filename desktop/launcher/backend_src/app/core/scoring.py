"""Scoring (Chinese / area rules).

A point is awarded to a color if it is occupied by that color, or if it is
empty and all adjacent reaching territory belongs to that color only.
Komi is added to white.
"""
from __future__ import annotations

from dataclasses import dataclass

from .board import GoBoard, EMPTY, BLACK, WHITE, opponent


@dataclass
class ScoreResult:
    black: int
    white: int
    komi: float
    winner: str  # "black" | "white" | "draw"
    margin: float  # positive => black wins
    territory_black: int
    territory_white: int

    def as_dict(self) -> dict:
        return {
            "black": self.black,
            "white": self.white,
            "komi": self.komi,
            "winner": self.winner,
            "margin": self.margin,
            "territory_black": self.territory_black,
            "territory_white": self.territory_white,
        }


def score_chinese(board: GoBoard, komi: float = 7.5) -> ScoreResult:
    size = board.size
    visited = [[False] * size for _ in range(size)]
    territory_black = 0
    territory_white = 0
    stone_black = 0
    stone_white = 0

    for y in range(size):
        for x in range(size):
            c = board.get(x, y)
            if c == BLACK:
                stone_black += 1
            elif c == WHITE:
                stone_white += 1
            elif c == EMPTY and not visited[y][x]:
                region: list[tuple[int, int]] = []
                borders: set[int] = set()
                stack = [(x, y)]
                while stack:
                    cx, cy = stack.pop()
                    if visited[cy][cx]:
                        continue
                    visited[cy][cx] = True
                    region.append((cx, cy))
                    for nx, ny in board.neighbors(cx, cy):
                        v = board.get(nx, ny)
                        if v == EMPTY:
                            if not visited[ny][nx]:
                                stack.append((nx, ny))
                        else:
                            borders.add(v)
                if borders == {BLACK}:
                    territory_black += len(region)
                elif borders == {WHITE}:
                    territory_white += len(region)
                # else: dame, no one scores

    black_total = stone_black + territory_black
    white_total = stone_white + territory_white + komi
    margin = black_total - white_total
    if margin > 0:
        winner = "black"
    elif margin < 0:
        winner = "white"
    else:
        winner = "draw"
    return ScoreResult(
        black=black_total,
        white=white_total,
        komi=komi,
        winner=winner,
        margin=margin,
        territory_black=territory_black,
        territory_white=territory_white,
    )
