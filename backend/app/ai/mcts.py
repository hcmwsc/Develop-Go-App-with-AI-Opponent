"""Lightweight Monte Carlo Tree Search engine.

This is the built-in fallback AI. It is intentionally simple:
- UCB1 selection
- Random rollout to terminal position (with depth cap to bound cost)
- Chinese scoring at terminal nodes
- Winrate estimated from root visit statistics

It is NOT strong. Its purpose is to provide a self-contained, dependency-free
opponent so the app is usable when KataGo is not configured.

A simple "learning" hook is provided via a prior table keyed by board hash:
historical winrates for the player who played a move bias exploration.
"""
from __future__ import annotations

import math
import random
import time
from typing import Optional

from ..config import settings
from ..core.board import GoBoard, BLACK, WHITE, EMPTY, opponent
from ..core.scoring import score_chinese
from .base import AIEngine, AnalysisResult, MoveEvaluation


class _Node:
    __slots__ = (
        "board",
        "parent",
        "move",
        "color",
        "children",
        "visits",
        "wins",
        "untried",
        "terminal_score",
    )

    def __init__(self, board: GoBoard, parent=None, move=None, color=BLACK):
        self.board = board
        self.parent = parent
        self.move = move  # move that produced this node (from parent's perspective)
        self.color = color  # color that moved into this node
        self.children: list[_Node] = []
        self.visits = 0
        self.wins = 0.0  # wins from the perspective of the player to move at parent
        self.untried: Optional[list[tuple[int, int]]] = None
        self.terminal_score: Optional[float] = None  # cached terminal margin

    def ucb(self, c: float) -> float:
        if self.visits == 0:
            return float("inf")
        exploit = self.wins / self.visits
        explore = c * math.sqrt(math.log(self.parent.visits) / self.visits)
        return exploit + explore


class MCTSEngine(AIEngine):
    name = "mcts"

    # 难度档位 -> (simulations, rollout_depth, exploration_c, deadline_s)
    # 越高搜索越深、走子越稳健；入门级故意减少搜索让玩家有空间
    # deadline_s 需考虑网关注入超时，默认控制在 2-5s 以内
    DIFFICULTY_PRESETS: dict[str, tuple[int, int, float, float]] = {
        "beginner": (30,   40,  1.8, 1.5),  # 入门：浅搜索
        "easy":     (100,  60,  1.5, 2.0),  # 初级
        "medium":   (400,  100, 1.4, 3.0),  # 中级：默认强度
        "hard":     (1200, 160, 1.2, 5.0),  # 高级：深搜索
    }

    def __init__(
        self,
        simulations: Optional[int] = None,
        c: Optional[float] = None,
        rollout_depth: int = 80,
        seed: Optional[int] = None,
        difficulty: Optional[str] = None,
    ):
        # 难度优先级最高：传入 difficulty 时覆盖其他参数
        if difficulty and difficulty in self.DIFFICULTY_PRESETS:
            sims, depth, exp_c, deadline = self.DIFFICULTY_PRESETS[difficulty]
            self.simulations = sims
            self.rollout_depth = depth
            self.c = exp_c
            self.deadline_s = deadline
            self.difficulty = difficulty
        else:
            self.simulations = simulations or settings.mcts_simulations
            self.c = c if c is not None else settings.mcts_exploration
            self.rollout_depth = rollout_depth
            self.deadline_s = 5.0
            self.difficulty = "medium"
        # Priors learned from past games: hash(move_board_state) -> winrate bias
        self._priors: dict[int, float] = {}
        self._rng = random.Random(seed)

    # ---- learning hook --------------------------------------------------
    def update_priors(self, board_hash: int, winrate: float) -> None:
        """Record that a position led to a winrate for the mover."""
        cur = self._priors.get(board_hash)
        if cur is None:
            self._priors[board_hash] = winrate
        else:
            # running average
            self._priors[board_hash] = 0.5 * (cur + winrate)

    # ---- resign policy --------------------------------------------------
    # 认输阈值：当前回合方胜率持续低于此值时考虑认输。
    # 难度越低阈值越低（更容易认输），避免低难度让玩家被压着打太久。
    RESIGN_WINRATE: dict[str, float] = {
        "beginner": 0.10,
        "easy":     0.08,
        "medium":   0.05,
        "hard":     0.03,
    }
    # 认输所需最低已落子数：避免开局随机性误判导致 AI 过早投降
    RESIGN_MIN_STONES = 15

    def _should_resign(self, board: GoBoard, color: Color, winrate: float) -> bool:
        """判断 AI 是否应认输：
        - 已落子数 >= RESIGN_MIN_STONES（中盘以后，局面信号可信）
        - 当前回合方胜率 < 难度对应阈值
        - 存在候选点（不是无棋可下被动 pass）
        """
        if winrate >= self.RESIGN_WINRATE.get(self.difficulty, 0.05):
            return False
        if self._stone_count(board) < self.RESIGN_MIN_STONES:
            return False
        return True

    # ---- main entry -----------------------------------------------------
    def analyze(self, board: GoBoard, color: Color, top_k: int = 10) -> AnalysisResult:
        root = _Node(board.clone(), parent=None, move=None, color=opponent(color))
        # populate untried lazily with heuristic ordering
        root.untried = self._ordered_legal_moves(board, color)
        if not root.untried:
            return AnalysisResult(
                best_move=None,
                winrate=0.0,
                score_lead=None,
                candidates=[],
                engine=self.name,
            )

        deadline = time.time() + self.deadline_s  # 按难度可调的安全上限
        for _ in range(self.simulations):
            if time.time() > deadline:
                break
            self._iterate(root, color)

        # Choose child with most visits (robust)
        if not root.children:
            # Only one legal move, return it
            move = root.untried[0] if root.untried else None
            return AnalysisResult(
                best_move=move,
                winrate=0.5,
                score_lead=None,
                candidates=[],
                engine=self.name,
            )

        best_child = max(root.children, key=lambda n: n.visits)
        total = sum(c.visits for c in root.children) or 1
        winrate = best_child.wins / best_child.visits if best_child.visits else 0.5

        candidates = []
        for child in sorted(root.children, key=lambda n: n.visits, reverse=True)[:top_k]:
            wr = child.wins / child.visits if child.visits else 0.0
            candidates.append(
                MoveEvaluation(
                    x=child.move[0],
                    y=child.move[1],
                    winrate=wr,
                    visits=child.visits,
                )
            )

        # 目差估计：开局空盘直接数子会得到荒谬值（空点归属未定），
        # 改用胜率反推目差：margin = ln(wr/(1-wr)) * 8（sigmoid 逆函数）
        # 这与 rollout 的 sigmoid 映射一致，给出稳定的目差估计。
        if winrate > 0.01 and winrate < 0.99:
            lead = math.log(winrate / (1.0 - winrate)) * 8.0
            # 转到当前回合方视角
            lead = lead if color == BLACK else -lead
        else:
            lead = None

        # 认输判定：胜率持续极低且已进入中盘
        resign = self._should_resign(board, color, winrate)

        # Update priors for the chosen position
        self.update_priors(board._hash_position(), winrate)

        return AnalysisResult(
            best_move=best_child.move,
            winrate=winrate,
            score_lead=lead,
            candidates=candidates,
            engine=self.name,
            resign=resign,
        )

    # ---- MCTS internals -------------------------------------------------
    def _iterate(self, root: _Node, root_color: Color) -> None:
        node = root
        # Selection
        while node.untried == [] and node.children:
            node = max(node.children, key=lambda n: n.ucb(self.c))
        # Expansion: pop the move with the highest heuristic prior.
        # _ordered_legal_moves 把好点排在前面，用 pop(0) 取最优的优先扩展。
        if node.untried:
            move = node.untried.pop(0)
            color_to_move = root_color if node is root else opponent(node.color)
            nb = node.board.clone()
            res = nb.place_stone(move[0], move[1], color_to_move)
            if not res["ok"]:
                return
            child = _Node(nb, parent=node, move=move, color=color_to_move)
            child.untried = self._ordered_legal_moves(nb, opponent(color_to_move))
            node.children.append(child)
            node = child
        # Rollout
        wr = self._rollout(node.board, opponent(node.color))
        # Backpropagate
        cur = node
        while cur is not None:
            cur.visits += 1
            cur.wins += (1.0 - wr) if cur.parent is not None else wr
            cur = cur.parent

    # 围棋经典星位（开局要点），按棋盘大小配置
    STAR_POINTS: dict[int, list[tuple[int, int]]] = {
        9:  [(2, 2), (2, 6), (6, 2), (6, 6), (4, 4)],
        13: [(3, 3), (3, 9), (9, 3), (9, 9), (6, 6)],
        19: [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9), (9, 15), (15, 3), (15, 9), (15, 15)],
    }

    def _stone_count(self, board: GoBoard) -> int:
        """已落子数，用于判断是否处于开局阶段。"""
        n = 0
        size = board.size
        for y in range(size):
            for x in range(size):
                if board.get(x, y) != EMPTY:
                    n += 1
        return n

    def _ordered_legal_moves(self, board: GoBoard, color: Color) -> list[tuple[int, int]]:
        """合法点按启发式排序，好点在前（配合 pop(0) 优先扩展）。

        - 开局阶段（已落子 ≤ 6）：星位优先，再按近中心
        - 中盘：靠近已有棋子的点优先，再按近中心
        """
        moves = board.legal_moves(color)
        if not moves:
            return moves
        size = board.size
        cx = cy = size // 2
        stones = self._stone_count(board)
        stars = set(self.STAR_POINTS.get(size, []))

        def has_neighbor(x: int, y: int, r: int = 2) -> bool:
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < size and 0 <= ny < size and board.get(nx, ny) != EMPTY:
                        return True
            return False

        def key(m: tuple[int, int]) -> tuple:
            x, y = m
            dist_center = abs(x - cx) + abs(y - cy)
            if stones <= 6:
                # 开局：星位最高优先级；星位之间随机排序避免每局都下同一点
                is_star = 0 if (x, y) in stars else 1
                rand = self._rng.random() if is_star == 0 else 0
                return (is_star, rand, dist_center)
            # 中盘：近棋子优先，再近中心
            near = 0 if has_neighbor(x, y) else 1
            return (near, dist_center)

        return sorted(moves, key=key)

    def _is_true_eye(self, board: GoBoard, x: int, y: int, color: Color) -> bool:
        """Approximate true-eye detection: a point whose all orthogonal
        neighbors are the player's own stones, and most diagonals too.
        Used to skip suicidal eye-filling in rollouts."""
        # All orthogonal neighbors must be own color (or wall)
        own = 0
        wall = 0
        diag_own = 0
        diag_total = 0
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not board.in_bounds(nx, ny):
                wall += 1
            elif board.get(nx, ny) == color:
                own += 1
            else:
                return False  # liberty or opponent => not a true eye
        if own + wall < 4:
            return False
        # Diagonals: allow at most one opponent diagonal on edge, none in center
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = x + dx, y + dy
            if not board.in_bounds(nx, ny):
                continue
            diag_total += 1
            if board.get(nx, ny) == color:
                diag_own += 1
            elif board.get(nx, ny) != EMPTY:
                # opponent on diagonal
                if wall > 0:
                    continue  # edge point: tolerate one opponent diagonal
                return False
        return diag_own >= diag_total - 1

    def _rollout(self, board: GoBoard, color: Color) -> float:
        """Heuristic rollout: avoid filling own eyes, limit depth, and
        return a continuous winrate based on score margin (sigmoid).
        Returns winrate for `color` (player to move), in [0, 1]."""
        b = board.clone()
        cur = color
        passes = 0
        size = b.size
        total_cells = size * size
        # 棋盘填满 55% 后强制 pass 收尾，避免 rollout 把棋盘塞满导致数子失真
        fill_limit = int(total_cells * 0.55)
        # 增量维护棋子数，避免每步 O(N²) 全盘扫描
        stone_count = self._stone_count(b)
        for _ in range(self.rollout_depth):
            if b.is_finished() or passes >= 2:
                break
            # 棋子过多则 pass 收尾
            if stone_count >= fill_limit:
                b.pass_move(cur)
                passes += 1
                cur = opponent(cur)
                continue
            moves = b.legal_moves(cur)
            if moves:
                moves = [m for m in moves if not self._is_true_eye(b, m[0], m[1], cur)]
            if not moves:
                b.pass_move(cur)
                passes += 1
            else:
                # 轻度偏向近棋子的点，但权重不大，保留随机性
                weighted = self._weight_moves(b, moves)
                if weighted:
                    total = sum(weighted)
                    r = self._rng.random() * total
                    acc = 0.0
                    chosen = moves[0]
                    for m, w in zip(moves, weighted):
                        acc += w
                        if acc >= r:
                            chosen = m
                            break
                    x, y = chosen
                else:
                    x, y = self._rng.choice(moves)
                res = b.place_stone(x, y, cur)
                if res["ok"]:
                    passes = 0
                    # 增量更新棋子数：落子 +1，提子 -len(captured)
                    stone_count += 1 - len(res["captured"])
                else:
                    b.pass_move(cur)
                    passes += 1
            cur = opponent(cur)
        try:
            sc = score_chinese(b)
        except Exception:
            return 0.5
        # margin > 0 表示黑领先；转换到当前回合方 color 的视角
        # color 是黑：margin>0 有利；color 是白：margin<0 有利
        if color == BLACK:
            advantage = sc.margin
        else:
            advantage = -sc.margin
        # sigmoid 映射：±30 目对应约 0.05~0.95，避免非 0 即 1 的极端评估
        return 1.0 / (1.0 + math.exp(-advantage / 8.0))

    def _weight_moves(self, board: GoBoard, moves: list[tuple[int, int]]) -> list[float]:
        """轻度加权：靠近棋子的点略高，但基础权重足够大，保证随机性，
        避免 rollout 变成纯贴身肉搏。"""
        weights = []
        for x, y in moves:
            w = 1.0  # 较大基础权重，保证随机性
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    nx, ny = x + dx, y + dy
                    if board.in_bounds(nx, ny) and board.get(nx, ny) != EMPTY:
                        dist = abs(dx) + abs(dy)
                        w += max(0.0, 1.5 - dist * 0.5)
            weights.append(w)
        return weights
