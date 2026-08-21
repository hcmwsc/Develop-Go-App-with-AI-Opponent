"""Core Go board with full rules: legality, captures, simple ko, scoring hook.

Board encoding: 0 = empty, 1 = black, 2 = white.
Coordinates: (x, y) with origin at top-left, x = column, y = row.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Iterable, Optional

EMPTY = 0
BLACK = 1
WHITE = 2
Color = int  # alias for clarity


def opponent(color: Color) -> Color:
    return WHITE if color == BLACK else BLACK


class GoBoard:
    """19x19 (configurable) Go board implementing Tromp-Taylor-ish rules.

    - Positional superko is approximated by tracking hashes of past positions.
    - Simple ko: the immediate recapture that would recreate the previous
      position is forbidden (covers the common single-stone ko case).
    - Suicide is forbidden.
    - Scoring is delegated to ``scoring.score_chinese``.
    """

    def __init__(self, size: int = 19):
        self.size = size
        self.grid: list[list[int]] = [[EMPTY] * size for _ in range(size)]
        self.captures: dict[int, int] = {BLACK: 0, WHITE: 0}
        self.history: list[int] = []  # hashes of past full positions
        # history 的 set 缓存，加速 is_legal 中 superko 判定的 in 查询
        self._history_set: set[int] = set()
        self.move_log: list[tuple[Optional[tuple[int, int]], Color]] = []
        self.ko_point: Optional[tuple[int, int]] = None
        self._record_position()

    # ---- geometry -------------------------------------------------------
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size

    def neighbors(self, x: int, y: int) -> Iterable[tuple[int, int]]:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny):
                yield nx, ny

    # ---- accessors ------------------------------------------------------
    def get(self, x: int, y: int) -> int:
        return self.grid[y][x]

    def at(self, x: int, y: int) -> int:
        return self.grid[y][x]

    # ---- groups & liberties --------------------------------------------
    def get_group(self, x: int, y: int) -> set[tuple[int, int]]:
        """Flood-fill the connected same-color group containing (x, y)."""
        color = self.grid[y][x]
        if color == EMPTY:
            return set()
        seen: set[tuple[int, int]] = set()
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen:
                continue
            seen.add((cx, cy))
            for nx, ny in self.neighbors(cx, cy):
                if self.grid[ny][nx] == color and (nx, ny) not in seen:
                    stack.append((nx, ny))
        return seen

    def group_liberties(self, group: set[tuple[int, int]]) -> set[tuple[int, int]]:
        libs: set[tuple[int, int]] = set()
        for x, y in group:
            for nx, ny in self.neighbors(x, y):
                if self.grid[ny][nx] == EMPTY:
                    libs.add((nx, ny))
        return libs

    def group_liberty_count(self, group: set[tuple[int, int]]) -> int:
        return len(self.group_liberties(group))

    # ---- legality -------------------------------------------------------
    def is_legal(self, x: int, y: int, color: Color) -> bool:
        if not self.in_bounds(x, y) or self.grid[y][x] != EMPTY:
            return False
        if self.ko_point == (x, y):
            return False
        # 增量模拟：直接改 grid，验证完手动还原，避免 deepcopy 整张棋盘
        opp = opponent(color)
        self.grid[y][x] = color
        captured: list[tuple[int, int]] = []
        for nx, ny in self.neighbors(x, y):
            if self.grid[ny][nx] == opp:
                grp = self.get_group(nx, ny)
                if self.group_liberty_count(grp) == 0:
                    captured.extend(grp)
        # 先应用提子，再查自身气数（"借提子而活"也算合法）
        for cx, cy in captured:
            self.grid[cy][cx] = EMPTY
        own = self.get_group(x, y)
        legal = self.group_liberty_count(own) > 0
        if legal:
            # superko: 结果局面必须未出现过
            legal = self._hash_position() not in self._history_set
        # 还原被提子（恢复 grid）
        for cx, cy in captured:
            self.grid[cy][cx] = opp
        # 还原落子
        self.grid[y][x] = EMPTY
        return legal

    def legal_moves(self, color: Color) -> list[tuple[int, int]]:
        moves = []
        for y in range(self.size):
            for x in range(self.size):
                if self.grid[y][x] == EMPTY and self.is_legal(x, y, color):
                    moves.append((x, y))
        return moves

    # ---- mutation -------------------------------------------------------
    def place_stone(self, x: int, y: int, color: Color) -> dict:
        """Place a stone, resolve captures, update ko.

        Returns a dict with: ok, captured (list of (x,y)), illegal_reason.
        Raises nothing on illegal move; caller checks ``ok``.
        """
        if not self.in_bounds(x, y) or self.grid[y][x] != EMPTY:
            return {"ok": False, "reason": "occupied", "captured": []}
        if self.ko_point == (x, y):
            return {"ok": False, "reason": "ko", "captured": []}
        if not self.is_legal(x, y, color):
            return {"ok": False, "reason": "illegal", "captured": []}

        self.grid[y][x] = color
        opp = opponent(color)
        captured: list[tuple[int, int]] = []
        for nx, ny in self.neighbors(x, y):
            if self.grid[ny][nx] == opp:
                grp = self.get_group(nx, ny)
                if self.group_liberty_count(grp) == 0:
                    captured.extend(grp)
        for cx, cy in captured:
            self.grid[cy][cx] = EMPTY
        self.captures[color] += len(captured)

        # Ko detection: single stone captured, single-stone group with one
        # liberty that is exactly the captured stone's position.
        self.ko_point = None
        if len(captured) == 1:
            own = self.get_group(x, y)
            if len(own) == 1 and self.group_liberty_count(own) == 1:
                self.ko_point = captured[0]

        self._record_position()
        self.move_log.append(((x, y), color))
        return {"ok": True, "captured": captured, "reason": None}

    def pass_move(self, color: Color) -> None:
        self.ko_point = None
        self.move_log.append((None, color))
        self._record_position()

    def to_move(self) -> Color:
        """Whose turn based on move log (black starts)."""
        if not self.move_log:
            return BLACK
        last_color = self.move_log[-1][1]
        return opponent(last_color)

    def _hash_position(self) -> int:
        return hash(tuple(tuple(row) for row in self.grid))

    def _record_position(self) -> None:
        h = self._hash_position()
        self.history.append(h)
        self._history_set.add(h)

    # ---- serialization --------------------------------------------------
    def to_flat(self) -> list[int]:
        return [cell for row in self.grid for cell in row]

    def to_grid(self) -> list[list[int]]:
        return deepcopy(self.grid)

    def clone(self) -> "GoBoard":
        nb = GoBoard(self.size)
        nb.grid = deepcopy(self.grid)
        nb.captures = dict(self.captures)
        nb.history = list(self.history)
        # 同步复制 set 缓存，避免引用共享
        nb._history_set = set(self._history_set)
        nb.move_log = list(self.move_log)
        nb.ko_point = self.ko_point
        return nb

    def is_finished(self) -> bool:
        """Game ends on two consecutive passes."""
        if len(self.move_log) < 2:
            return False
        return self.move_log[-1][0] is None and self.move_log[-2][0] is None
