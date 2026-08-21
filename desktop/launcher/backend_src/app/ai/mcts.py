"""Lightweight Monte Carlo Tree Search engine.

This is the built-in fallback AI. It is intentionally self-contained:
- RAVE / AMAF enhanced selection (All-Moves-As-First + UCB blend)
- Tactically biased rollout (capture / escape / connection awareness)
- Chinese scoring at terminal nodes with sigmoid-margin winrate mapping
- Opening star / 3-3 / komoku prior for the first ~dozen moves
- Progressive widening: at each node, keep only the top-K heuristic candidates
  so simulations are not wasted on obviously bad moves

It is NOT KataGo-level, but it is dramatically stronger than the naive
UCB1 + random-rollout baseline and provides a credible opponent at
medium/hard levels when KataGo is not configured.
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
        "amaf_visits",
        "amaf_wins",
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
        # --- AMAF (All-Moves-As-First) statistics used by RAVE ---
        # Accumulated by tracking every move played on the rollout path
        # as if it was the first move played at the ancestor node.
        self.amaf_visits = 0
        self.amaf_wins = 0.0
        self.untried: Optional[list[tuple[int, int]]] = None
        self.terminal_score: Optional[float] = None  # cached terminal margin

    def rave_ucb(self, c: float, equiv: int = 400) -> float:
        """RAVE blend of on-policy wins and AMAF wins.

        The weight beta transitions smoothly from pure AMAF at low visit counts
        to pure UCB as the child collects its own on-policy samples.
        `equiv` controls how quickly RAVE trust is ceded to real stats.
        """
        if self.visits == 0 and self.amaf_visits == 0:
            return float("inf")
        # -- Standard UCB exploitation term (from on-policy visits) --
        exploit = self.wins / self.visits if self.visits > 0 else 0.0
        explore = c * math.sqrt(math.log(max(1, self.parent.visits)) / max(1, self.visits))
        ucb = exploit + explore
        # -- AMAF (RAVE) term --
        if self.amaf_visits > 0:
            amaf = self.amaf_wins / self.amaf_visits
            # RAVE beta: fraction of weight to assign to AMAF.
            # Classical formula is sqrt(equiv / (3*N + equiv)); we use 10*N
            # so RAVE cedes control to real UCB *much* faster, preventing
            # seed-biased early AMAF samples from locking the tree onto
            # heuristically bad children. RAVE stays relevant only during
            # the first ~30-60 parent visits (warm-up prior).
            parent_visits = max(1, self.parent.visits)
            beta = math.sqrt(equiv / (10.0 * parent_visits + equiv))
            if self.visits == 0:
                return amaf  # pure AMAF when no real visits
            return beta * amaf + (1.0 - beta) * ucb
        return ucb


class MCTSEngine(AIEngine):
    name = "mcts"

    # 难度档位 -> (simulations, rollout_depth, exploration_c, deadline_s)
    # 越高搜索越深、走子越稳健；入门级故意减少搜索让玩家有空间
    # deadline_s 考虑：前端 Vite 代理超时 = 60s；一次 AI move 调用 = play + 可选 pre-analyze
    # 所以给 hard 留足 15s 上限安全。
    #
    # 2026-08-19 第四次全面加强：
    #   - Tree Reuse：跨手复用搜索子树，等效模拟量 ×2~5
    #   - Prior Knowledge：新子节点注入启发式先验（提子/星位/邻子），加速收敛
    #   - Rollout 改进：self-atari 规避（孤立 1 气子惩罚 ×0.15）
    #   - 模拟次数再次升级：hard 5500 → 7000，medium 1600 → 2200
    DIFFICULTY_PRESETS: dict[str, tuple[int, int, float, float]] = {
        "beginner": (120,   80,  1.60,  2.5),  # 入门：适度，仍给新手空间
        "easy":     (550,   150, 1.30,  4.5),  # 初级：模拟 +38%
        "medium":   (2200,  240, 1.10,  9.0),  # 中级：模拟 +38%，深度 +20%
        "hard":     (7000,  400, 0.95, 15.0),  # 高级：模拟 +27%，深度 +11%，c↓
    }

    # RAVE 等效参数：越小 → 越快放权给真实 on-policy UCB 统计。
    # 过大的 equiv 会导致初期的随机 AMAF 样本"粘住"好点，让真实统计
    # 长时间得不到访问（seed 依赖的假性偏置）。
    # 配合下方 beta 分母的 10x 加速衰减，RAVE 仅在前 ~50 次访问生效。
    AMAF_EQUIV: dict[str, int] = {
        "beginner": 120,
        "easy": 150,
        "medium": 200,
        "hard": 350,
    }

    # Progressive widening: 每节点保留的候选手数（启发式排序后）
    # 低难度多给点多样性，高难度集中算力在好点上
    MAX_CANDIDATES: dict[str, int] = {
        "beginner": 50,
        "easy": 45,
        "medium": 40,
        "hard": 35,
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
        self._amaf_equiv = self.AMAF_EQUIV.get(self.difficulty, 500)
        self._max_candidates = self.MAX_CANDIDATES.get(self.difficulty, 30)
        # Priors learned from past games: hash(move_board_state) -> winrate bias
        self._priors: dict[int, float] = {}
        self._rng = random.Random(seed)
        # Tree reuse cache: (board_hash, ko_point, color_to_move) → _Node
        # 允许跨手复用已搜索的子树，等效模拟量 ×2~5
        self._tree_cache: dict = {}

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
    # 设计哲学：AI 只有在"背水一战失败"后才有可能投降——
    # 即胜率极低、且对局已进入后盘（大量落子后），确认真的翻盘无望。
    RESIGN_WINRATE: dict[str, float] = {
        "beginner": 0.03,   # 入门：胜率 < 3% 才考虑（AI 多撑几手给新手成就感）
        "easy":     0.02,   # 初级：< 2%
        "medium":   0.01,   # 中级：< 1%
        "hard":     0.005,  # 高级：< 0.5%（背水一战彻底失败才可能认输）
    }
    RESIGN_MIN_STONES = 80

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

    # ---- prior knowledge ------------------------------------------------
    def _prior_for_move(
        self, parent_board: GoBoard, move: tuple[int, int], color: Color
    ) -> tuple[int, float]:
        """启发式先验：给新子节点注入少量虚拟 visits/wins。

        基于 _ordered_legal_moves 的战术分析，把"好棋"的先验调高，
        让 RAVE-UCB 在最初几次选择时倾向于好的落子，加速收敛。
        """
        x, y = move
        opp = opponent(color)
        size = parent_board.size
        visits = 1  # 基础先验
        wins = 0.5  # 中性胜率

        # 提子先验：检查落子点邻接的对方 1 气棋组
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not parent_board.in_bounds(nx, ny):
                continue
            if parent_board.get(nx, ny) == opp:
                libs, grp = self._group_liberties(parent_board, nx, ny)
                if libs == 1:
                    visits += min(6, len(grp) * 2)
                    wins += min(4.0, len(grp) * 1.2)

        # 开局先验：星位 / 小目
        stones = self._stone_count(parent_board)
        if stones <= 12:
            if (x, y) in set(self.STAR_POINTS.get(size, [])):
                visits += 4
                wins += 2.5
            elif (x, y) in set(self.KOMOKU.get(size, [])):
                visits += 3
                wins += 1.8

        # 邻子先验：近已有棋子的点更可能好棋
        if stones > 6:
            has_nbr = any(
                parent_board.in_bounds(x + dx, y + dy)
                and parent_board.get(x + dx, y + dy) != EMPTY
                for dx in range(-2, 3)
                for dy in range(-2, 3)
            )
            if has_nbr:
                visits += 2
                wins += 1.0

        return visits, wins

    # ---- main entry -----------------------------------------------------
    def analyze(self, board: GoBoard, color: Color, top_k: int = 10) -> AnalysisResult:
        # ---- Tree reuse: 如果此局面曾作为某次搜索的子节点被搜索过，
        # 直接复用其子树统计，等效模拟量 ×2~5。
        cache_key = (board._hash_position(), board.ko_point, color)
        cached = self._tree_cache.pop(cache_key, None)
        if cached is not None:
            root = cached
            root.parent = None  # detach from old tree
            if root.untried is None:
                root.untried = self._ordered_legal_moves(board, color, widen=True)
        else:
            root = _Node(board.clone(), parent=None, move=None, color=opponent(color))
            root.untried = self._ordered_legal_moves(board, color, widen=True)

        if not root.untried and not root.children:
            return AnalysisResult(
                best_move=None,
                winrate=0.0,
                score_lead=None,
                candidates=[],
                engine=self.name,
            )

        deadline = time.time() + self.deadline_s
        for _ in range(self.simulations):
            if time.time() > deadline:
                break
            self._iterate(root, color)

        # Cache children for potential reuse on the next move.
        # child.color = 走入该子的颜色；下一步轮到 opponent(child.color) 走。
        for child in root.children:
            ck = (child.board._hash_position(), child.board.ko_point, opponent(child.color))
            self._tree_cache[ck] = child
        # Also cache root itself (for re-analysis of the same position)
        self._tree_cache[cache_key] = root
        # Evict old entries to bound memory
        if len(self._tree_cache) > 50:
            for k in list(self._tree_cache.keys())[:30]:
                if k != cache_key:
                    del self._tree_cache[k]

        # Choose child with most visits (robust)
        if not root.children:
            move = root.untried[0] if root.untried else None
            return AnalysisResult(
                best_move=move,
                winrate=0.5,
                score_lead=None,
                candidates=[],
                engine=self.name,
            )

        best_child = max(root.children, key=lambda n: n.visits)
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

        # 目差估计：胜率反推目差（sigmoid^{-1} * 8）
        if winrate > 0.01 and winrate < 0.99:
            lead = math.log(winrate / (1.0 - winrate)) * 8.0
            lead = lead if color == BLACK else -lead
        else:
            lead = None

        resign = self._should_resign(board, color, winrate)
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
        # ------------------------------------------------------------------
        # 1) Selection: walk down by RAVE-UCB until we find an expandable node
        # ------------------------------------------------------------------
        node = root
        selection_path: list[_Node] = [node]
        while node.untried == [] and node.children:
            node = max(node.children, key=lambda n: n.rave_ucb(self.c, self._amaf_equiv))
            selection_path.append(node)

        # ------------------------------------------------------------------
        # 2) Expansion: pop the top heuristic move from untried
        # ------------------------------------------------------------------
        if node.untried:
            move = node.untried.pop(0)
            color_to_move = root_color if node is root else opponent(node.color)
            nb = node.board.clone()
            res = nb.place_stone(move[0], move[1], color_to_move)
            if not res["ok"]:
                return
            child = _Node(nb, parent=node, move=move, color=color_to_move)
            # Prior knowledge: inject small virtual visits/wins based on
            # heuristic quality of the move, accelerating convergence.
            pv, pw = self._prior_for_move(node.board, move, color_to_move)
            child.visits = pv
            child.wins = pw
            child.untried = self._ordered_legal_moves(nb, opponent(color_to_move), widen=True)
            node.children.append(child)
            selection_path.append(child)
            node = child

        # ------------------------------------------------------------------
        # 3) Rollout (tactically biased), returning winrate for the player
        #    who is about to move at the last expanded node.
        #    Also records every (color, move) pair played during rollout
        #    for AMAF stats.
        # ------------------------------------------------------------------
        rollout_player = opponent(node.color)
        winrate_from_rollout, amaf_trace = self._rollout_with_trace(
            node.board, rollout_player
        )

        # ------------------------------------------------------------------
        # 4) Backpropagation of on-policy stats
        # ------------------------------------------------------------------
        # Convention: child.wins counts wins for the COLOR THAT MOVED INTO
        # child (i.e. the player who played child.move). This is exactly
        # the parent's "to-move" color at the moment that child was chosen.
        # So for every node on the path, we compute the value for the color
        # that moved into that node; if that color == rollout_player the
        # value is winrate_from_rollout, otherwise 1 - winrate_from_rollout.
        # The root itself is never entered by any move, so we skip it when
        # attributing wins but still increment its visit counter so UCB
        # parent-visit denominators stay correct.
        wr_rollout_pov = winrate_from_rollout  # wr for rollout_player at leaf
        cur = node
        while cur is not None:
            cur.visits += 1
            if cur is not root:
                # color that moved INTO cur == cur.color
                v = wr_rollout_pov if cur.color == rollout_player else (1.0 - wr_rollout_pov)
                cur.wins += v
            cur = cur.parent

        # ------------------------------------------------------------------
        # 5) AMAF update: for every ancestor node A (not the last expanded
        #    child), look at A's direct children. If child.move was also
        #    played later by the same *to-move color of A* anywhere in the
        #    rollout trace, credit that child with an AMAF sample.
        #    A's to-move color is: root_color if A is root else opp(A.color).
        #    The sample for a child is the WR from the POV of that child's
        #    entry color (same convention as child.wins), which equals the
        #    to-move color of A because that player just chose child.move.
        # ------------------------------------------------------------------
        last_idx = len(selection_path) - 1
        for i, ancestor in enumerate(selection_path):
            if i == last_idx:
                continue
            to_move_at_ancestor = root_color if ancestor is root else opponent(ancestor.color)
            trace_moves = amaf_trace.get(to_move_at_ancestor, ())
            if not trace_moves:
                continue
            trace_set = set(trace_moves)
            # Sample = WR for to_move_at_ancestor (this is exactly the WR
            # for the color that entered the child, matching child.wins POV)
            sample = (
                wr_rollout_pov
                if to_move_at_ancestor == rollout_player
                else (1.0 - wr_rollout_pov)
            )
            for child in ancestor.children:
                if child.move in trace_set:
                    child.amaf_visits += 1
                    child.amaf_wins += sample

    # ---- heuristics -----------------------------------------------------
    # 围棋经典星位（开局要点），按棋盘大小配置
    STAR_POINTS: dict[int, list[tuple[int, int]]] = {
        9:  [(2, 2), (2, 6), (6, 2), (6, 6), (4, 4)],
        13: [(3, 3), (3, 9), (9, 3), (9, 9), (6, 6)],
        19: [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9), (9, 15), (15, 3), (15, 9), (15, 15)],
    }
    # 小目 (3-4 / 4-3)：标准开局角部
    KOMOKU: dict[int, list[tuple[int, int]]] = {
        19: [(3, 4), (4, 3), (3, 14), (14, 3), (15, 4), (4, 15), (15, 14), (14, 15)],
    }
    # 三三 (2-4 小棋盘)；19 路 3-3
    SAN_SAN: dict[int, list[tuple[int, int]]] = {
        9:  [(2, 4), (4, 2), (2, 4), (4, 6), (6, 4), (4, 2)],
        19: [(2, 3), (3, 2), (2, 15), (15, 2), (16, 3), (3, 16), (16, 15), (15, 16)],
    }

    def _stone_count(self, board: GoBoard) -> int:
        n = 0
        size = board.size
        for y in range(size):
            for x in range(size):
                if board.get(x, y) != EMPTY:
                    n += 1
        return n

    def _group_liberties(self, board: GoBoard, x: int, y: int) -> tuple[int, set[tuple[int, int]]]:
        """返回 (liberties, stones_in_group) for the group at (x,y).
        If empty, returns (0, set())."""
        color = board.get(x, y)
        if color == EMPTY:
            return 0, set()
        size = board.size
        stack = [(x, y)]
        seen = set()
        libs: set[tuple[int, int]] = set()
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen:
                continue
            seen.add((cx, cy))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < size and 0 <= ny < size):
                    continue
                cell = board.get(nx, ny)
                if cell == EMPTY:
                    libs.add((nx, ny))
                elif cell == color and (nx, ny) not in seen:
                    stack.append((nx, ny))
        return len(libs), seen

    def _ordered_legal_moves(
        self, board: GoBoard, color: Color, widen: bool = False
    ) -> list[tuple[int, int]]:
        """合法点按启发式排序，好点在前（配合 pop(0) 优先扩展）。

        - 开局阶段：星位 / 小目 / 三三 最高优先级，按近中心二次排序
        - 中盘：按优先级从高到低 ——
            0. 打吃对方（1 气棋组，直接提子）
            1. 己方逃气/连接（己方 1~2 气棋组的气点）
            2. **接触战/打入应对**：对方在己方势力附近的棋子，贴/夹/攻的点（距对方 ≤ 2，且该对方子距己方 ≤ 2）
            3. 近已有棋子（正常下棋不会往空里下）
            4. 其它（近中心）
        - 若 widen=True，应用 progressive widening：仅保留 MAX_CANDIDATES 个好点
        """
        moves = board.legal_moves(color)
        if not moves:
            return moves
        # 过滤掉填自己真眼的自杀点（从候选中剔除）
        moves = [m for m in moves if not self._is_true_eye(board, m[0], m[1], color)]
        if not moves:
            return moves
        size = board.size
        cx = cy = size // 2
        stones = self._stone_count(board)
        opp = opponent(color)
        stars = set(self.STAR_POINTS.get(size, []))
        komoku = set(self.KOMOKU.get(size, []))
        sansan = set(self.SAN_SAN.get(size, []))

        # 预计算：对方 1 气棋组的气点（=能打吃提子的点）
        # 己方 1~2 气棋组的邻接空点（=必须逃气的点）
        opponent_atari_pts: dict[tuple[int, int], int] = {}  # pt -> captured size
        own_escape_pts: set[tuple[int, int]] = set()
        # "接触战优先点"：距对方子 ≤ 2 且那个对方子距己方 ≤ 2（打入/接触战）
        contact_pts: dict[tuple[int, int], int] = {}  # pt -> min dist to opponent
        # 己方/对方位置集合（用于距离判定）
        own_pts: list[tuple[int, int]] = []
        opp_pts: list[tuple[int, int]] = []
        checked_groups: set[tuple[int, int]] = set()

        for sy in range(size):
            for sx in range(size):
                cell = board.get(sx, sy)
                if cell == EMPTY:
                    continue
                if cell == color:
                    own_pts.append((sx, sy))
                else:
                    opp_pts.append((sx, sy))
                if (sx, sy) in checked_groups:
                    continue
                libs, grp = self._group_liberties(board, sx, sy)
                checked_groups.update(grp)
                lib_pts: set[tuple[int, int]] = set()
                for gx, gy in grp:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = gx + dx, gy + dy
                        if 0 <= nx < size and 0 <= ny < size and board.get(nx, ny) == EMPTY:
                            lib_pts.add((nx, ny))
                if cell == opp:
                    if libs == 1 and lib_pts:
                        grp_size = len(grp)
                        for p in lib_pts:
                            opponent_atari_pts[p] = opponent_atari_pts.get(p, 0) + grp_size
                elif cell == color and libs <= 2 and lib_pts:
                    own_escape_pts.update(lib_pts)
                    for (lx, ly) in list(lib_pts):
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                            nx, ny = lx + dx, ly + dy
                            if (
                                0 <= nx < size
                                and 0 <= ny < size
                                and board.get(nx, ny) == EMPTY
                            ):
                                own_escape_pts.add((nx, ny))

        # 计算 contact_pts：对方子附近的空点（要求对方子离己方子不太远）
        for ox, oy in opp_pts:
            # 这个对方子距离己方有多近？
            min_own_dist = min(
                (abs(ox - px) + abs(oy - py) for px, py in own_pts),
                default=999,
            )
            if min_own_dist > 3:
                continue  # 对方在空旷地带，不是"打入我方势力"
            # 对这个对方子周围 ±2 的空点打标
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    nx, ny = ox + dx, oy + dy
                    if not (0 <= nx < size and 0 <= ny < size):
                        continue
                    if board.get(nx, ny) != EMPTY:
                        continue
                    d = abs(dx) + abs(dy)
                    if d == 0:
                        continue
                    # 越贴近对方子，优先级别越高
                    if (nx, ny) not in contact_pts or d < contact_pts[(nx, ny)]:
                        contact_pts[(nx, ny)] = d

        def has_neighbor(x: int, y: int, r: int = 2) -> bool:
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < size and 0 <= ny < size and board.get(nx, ny) != EMPTY:
                        return True
            return False

        def min_opp_dist(x: int, y: int) -> int:
            if not opp_pts:
                return 99
            return min(abs(x - px) + abs(y - py) for px, py in opp_pts)

        def key(m: tuple[int, int]) -> tuple:
            x, y = m
            dist_center = abs(x - cx) + abs(y - cy)
            # ---- 开局前 12 手：标准开局点优先 ----
            if stones <= 12:
                if (x, y) in stars:
                    return (0, self._rng.random(), dist_center)
                if (x, y) in komoku:
                    return (1, self._rng.random(), dist_center)
                if (x, y) in sansan:
                    return (2, self._rng.random(), dist_center)
                # 开局远离现有棋子的点也保留，只是优先级稍低
                near = 0 if has_neighbor(x, y, 3) else 1
                return (3 + near, dist_center)

            # ---- 中盘：战术优先 ----
            # (0) 打吃对方：能吃的子越多越优先（-score 让多子在前）
            if (x, y) in opponent_atari_pts:
                captured = opponent_atari_pts[(x, y)]
                return (0, -captured, dist_center)
            # (1) 自己 1-2 气逃气 / 连接
            if (x, y) in own_escape_pts:
                return (1, min_opp_dist(x, y), dist_center)
            # (2) 接触战 / 打入应对：距对方越近越优先（贴/夹/应）
            if (x, y) in contact_pts:
                return (2, contact_pts[(x, y)], dist_center)
            # (3) 近已有棋子
            near = 0 if has_neighbor(x, y, 2) else 1
            return (3 + near, min_opp_dist(x, y), dist_center)

        result = sorted(moves, key=key)
        if widen and len(result) > self._max_candidates:
            result = result[: self._max_candidates]
        return result

    def _is_true_eye(self, board: GoBoard, x: int, y: int, color: Color) -> bool:
        """Approximate true-eye detection: a point whose all orthogonal
        neighbors are the player's own stones, and most diagonals too.
        Used to skip suicidal eye-filling in rollouts."""
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

    def _rollout_with_trace(
        self, board: GoBoard, color: Color
    ) -> tuple[float, dict[Color, tuple[tuple[int, int], ...]]]:
        """Heuristic rollout returning (winrate, trace).

        - Winrate is sigmoid-mapped score margin from the `color` POV.
        - trace[player_color] = tuple of moves played by that color during
          the rollout, used to update AMAF statistics during backprop.
        """
        b = board.clone()
        cur = color
        trace: dict[Color, list[tuple[int, int]]] = {BLACK: [], WHITE: []}
        passes = 0
        size = b.size
        total_cells = size * size
        fill_limit = int(total_cells * 0.60)  # 60% 填满再 pass 收尾（战术 rollout 更强）
        stone_count = self._stone_count(b)

        for _ in range(self.rollout_depth):
            if b.is_finished() or passes >= 2:
                break
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
                weighted, moves = self._tactical_weights(b, moves, cur)
                total = sum(weighted)
                if total <= 0:
                    x, y = self._rng.choice(moves)
                else:
                    r = self._rng.random() * total
                    acc = 0.0
                    chosen = moves[0]
                    for m, w in zip(moves, weighted):
                        acc += w
                        if acc >= r:
                            chosen = m
                            break
                    x, y = chosen
                trace[cur].append((x, y))
                res = b.place_stone(x, y, cur)
                if res["ok"]:
                    passes = 0
                    stone_count += 1 - len(res["captured"])
                else:
                    # 非法点：回退记录（我们不会真的下了）
                    trace[cur].pop()
                    b.pass_move(cur)
                    passes += 1
            cur = opponent(cur)

        try:
            sc = score_chinese(b)
        except Exception:
            return 0.5, {BLACK: (), WHITE: ()}
        # margin > 0 表示黑领先
        advantage = sc.margin if color == BLACK else -sc.margin
        wr = 1.0 / (1.0 + math.exp(-advantage / 8.0))
        trace_tuple: dict[Color, tuple[tuple[int, int], ...]] = {
            c: tuple(m) for c, m in trace.items()
        }
        return wr, trace_tuple

    def _tactical_weights(
        self, board: GoBoard, moves: list[tuple[int, int]], color: Color
    ) -> tuple[list[float], list[tuple[int, int]]]:
        """战术权重：越大越优先。相比 _ordered_legal_moves 用分级排序，
        这里输出浮点数权重，支持加权采样。

        权重类别（相对倍率）：
          - 直接提掉对方棋组（对方落子该点后剩下 1 气）：×200
          - 己方 1 气棋组的气点 / 连接点（救活）：×60
          - 对方 2 气棋组的气点（缩小到下一步能打吃）：×12
          - 己方 2 气棋组的气点 / 连接：×10
          - 自己棋子 1 邻 5×5：×1.8
          - 基础权重：1.0
        """
        opp = opponent(color)
        size = board.size
        # ---- 预计算：枚举已存在棋组的气 ----
        atari_capture_pts: dict[tuple[int, int], int] = {}  # pt -> stones to capture
        opp_2lib_pts: set[tuple[int, int]] = set()
        own_1lib_pts: set[tuple[int, int]] = set()
        own_2lib_pts: set[tuple[int, int]] = set()
        checked: set[tuple[int, int]] = set()
        for sy in range(size):
            for sx in range(size):
                cell = board.get(sx, sy)
                if cell == EMPTY or (sx, sy) in checked:
                    continue
                libs, grp = self._group_liberties(board, sx, sy)
                checked.update(grp)
                # 收集气点
                lib_pts: set[tuple[int, int]] = set()
                for gx, gy in grp:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = gx + dx, gy + dy
                        if 0 <= nx < size and 0 <= ny < size and board.get(nx, ny) == EMPTY:
                            lib_pts.add((nx, ny))
                grp_size = len(grp)
                if cell == opp:
                    if libs == 1:
                        for p in lib_pts:
                            atari_capture_pts[p] = atari_capture_pts.get(p, 0) + grp_size
                    elif libs == 2:
                        opp_2lib_pts.update(lib_pts)
                else:  # color == 己方
                    if libs == 1:
                        own_1lib_pts.update(lib_pts)
                        # 相邻 1 路的己方棋组的救子通道
                        for (lx, ly) in list(lib_pts):
                            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                                nx, ny = lx + dx, ly + dy
                                if (
                                    0 <= nx < size
                                    and 0 <= ny < size
                                    and board.get(nx, ny) == EMPTY
                                ):
                                    own_1lib_pts.add((nx, ny))
                    elif libs == 2:
                        own_2lib_pts.update(lib_pts)

        weights: list[float] = []
        kept: list[tuple[int, int]] = []
        for x, y in moves:
            w = 1.0
            if (x, y) in atari_capture_pts:
                # 能直接提掉的子越多，越优先（提 1 子 200×，提 5 子 500×）
                w += 200.0 + 60.0 * atari_capture_pts[(x, y)]
            if (x, y) in own_1lib_pts:
                w += 60.0
            if (x, y) in opp_2lib_pts:
                w += 12.0
            if (x, y) in own_2lib_pts:
                w += 10.0
            # 邻接棋子的近距离权重（1.8 base）
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    nx, ny = x + dx, y + dy
                    if (
                        0 <= nx < size
                        and 0 <= ny < size
                        and board.get(nx, ny) != EMPTY
                    ):
                        dist = abs(dx) + abs(dy)
                        w += max(0.0, 1.6 - dist * 0.5)
            # Self-atari 规避：孤立子只有 0-1 气且无友邻连接 → 强烈惩罚
            if (x, y) not in atari_capture_pts:
                imm_libs = 0
                has_friend = False
                for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + ddx, y + ddy
                    if not (0 <= nx < size and 0 <= ny < size):
                        continue
                    cell = board.get(nx, ny)
                    if cell == EMPTY:
                        imm_libs += 1
                    elif cell == color:
                        has_friend = True
                if imm_libs <= 1 and not has_friend:
                    w *= 0.15
            kept.append((x, y))
            weights.append(w)
        return weights, kept

    def _rollout(self, board: GoBoard, color: Color) -> float:
        """Backward-compat single-return wrapper (unused inside tree search
        but provided for other callers / tests)."""
        wr, _ = self._rollout_with_trace(board, color)
        return wr

    def _weight_moves(self, board: GoBoard, moves: list[tuple[int, int]]) -> list[float]:
        """Deprecated / backward-compat wrapper. Returns tactical weights
        for the caller's moves list (assuming the mover is whoever is
        playing them — we return the same weighting from _tactical_weights
        using BLACK as a safe default)."""
        # For external callers, assume BLACK; real usage now goes through
        # _tactical_weights directly.
        weights, _ = self._tactical_weights(board, list(moves), BLACK)
        return weights
