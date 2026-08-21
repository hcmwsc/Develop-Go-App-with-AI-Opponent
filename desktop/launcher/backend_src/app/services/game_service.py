"""In-memory game session management.

Games are keyed by a short uuid. For a real deployment you'd swap this for
Redis or a database; the scaffold keeps everything in-process.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from ..core.board import GoBoard, BLACK, WHITE, EMPTY, Color, opponent
from ..core.scoring import score_chinese
from ..core.rules import export_sgf
from ..ai import get_engine, AnalysisResult
from ..ai.base import AIEngine
from ..ai.manager import create_engine
from ..models.schemas import (
    GameState,
    PlayResponse,
    CandidateMove,
    MoveInfo,
    ReviewEntry,
    ReviewResponse,
)


COLOR_NAME = {BLACK: "black", WHITE: "white"}
NAME_COLOR = {v: k for k, v in COLOR_NAME.items()}


@dataclass
class GameSession:
    game_id: str
    board: GoBoard
    komi: float
    human_color: Color
    ai_color: Color
    difficulty: str = "medium"
    engine: AIEngine = None  # type: ignore[assignment]  # set in __post_init__
    finished: bool = False
    history_snapshots: list = field(default_factory=list)  # for undo
    # 复盘数据：每一步落子后追加一条记录（move_number 从 1 开始；0 为初始局面）
    review_log: list[dict] = field(default_factory=list)
    # 上一步走子前对当前回合方的分析结果，用于在本步走子后记录"本步走子前胜率"
    _pending_pre_analysis: Optional[AnalysisResult] = None

    def __post_init__(self) -> None:
        if self.engine is None:
            self.engine = create_engine(self.difficulty)

    def to_state(self) -> GameState:
        score = None
        if self.finished:
            score = score_chinese(self.board, self.komi).as_dict()
        return GameState(
            game_id=self.game_id,
            board=self.board.to_grid(),
            board_size=self.board.size,
            komi=self.komi,
            to_move=COLOR_NAME[self.board.to_move()],
            captures={
                "black": self.board.captures[BLACK],
                "white": self.board.captures[WHITE],
            },
            move_log=[
                MoveInfo(x=x, y=y, color=COLOR_NAME[c]) if (x, y) else None
                for (x, y), c in self.board.move_log
            ],
            finished=self.finished,
            score=score,
            difficulty=self.difficulty,
            engine=self.engine.name if self.engine else None,
        )

    def _append_review_entry(
        self,
        move: Optional[tuple[int, int]],
        color: str,
        pre_analysis: Optional[AnalysisResult],
        post_analysis: Optional[AnalysisResult] = None,
    ) -> None:
        """记录一步落子到复盘日志。

        - move: 落子坐标，None 表示 pass
        - color: "black" | "white"
        - pre_analysis: 本步走子前对当前回合方的分析（含本步走子前胜率/推荐点）
        - post_analysis: 本步走子后的分析（可选，目前仅 AI 应手时提供）
        """
        move_number = len(self.review_log) + 1
        # 走子前胜率（从当前回合方视角，即即将走子的一方）
        pre_winrate = pre_analysis.winrate if pre_analysis else None
        pre_score_lead = pre_analysis.score_lead if pre_analysis else None
        # 推荐的最佳应手（本步走子前 AI 推荐的）
        best_move = pre_analysis.best_move if pre_analysis else None
        candidates = []
        if pre_analysis:
            for c in pre_analysis.candidates:
                candidates.append({
                    "x": c.x, "y": c.y,
                    "winrate": c.winrate,
                    "visits": c.visits,
                    "score_lead": c.score_lead,
                    "prior": c.prior,
                })
        # 走子后胜率：取 post_analysis（AI 应手时为 AI 分析的胜率），
        # 否则用 pre_analysis 的胜率作为近似（人走子后没立即分析）
        post_winrate = post_analysis.winrate if post_analysis else pre_winrate
        post_score_lead = post_analysis.score_lead if post_analysis else pre_score_lead

        self.review_log.append({
            "move_number": move_number,
            "move": list(move) if move else None,
            "color": color,
            "pre_winrate": pre_winrate,
            "post_winrate": post_winrate,
            "pre_score_lead": pre_score_lead,
            "post_score_lead": post_score_lead,
            "best_move": list(best_move) if best_move else None,
            "candidates": candidates,
        })

    def to_review(self) -> ReviewResponse:
        """生成复盘数据：每步的分析 + 初始棋盘 + move_log。
        前端可用 move_log 重放重建任意步的棋盘。"""
        entries: list[ReviewEntry] = []
        prev_wr: Optional[float] = None
        for r in self.review_log:
            # 关键转折点：胜率变化超过 15%（任何一方）
            is_key = False
            if prev_wr is not None and r["post_winrate"] is not None:
                # 把胜率统一到黑方视角便于比较
                def black_view(wr: Optional[float], col: str) -> Optional[float]:
                    if wr is None:
                        return None
                    return wr if col == "black" else 1.0 - wr
                pre_b = black_view(r["pre_winrate"], r["color"])
                post_b = black_view(r["post_winrate"], r["color"])
                if pre_b is not None and post_b is not None:
                    is_key = abs(post_b - pre_b) > 0.15
            entries.append(ReviewEntry(
                move_number=r["move_number"],
                move=r["move"],
                color=r["color"],
                pre_winrate=r["pre_winrate"],
                post_winrate=r["post_winrate"],
                pre_score_lead=r["pre_score_lead"],
                post_score_lead=r["post_score_lead"],
                best_move=r["best_move"],
                candidates=r["candidates"],
                is_key_move=is_key,
            ))
            prev_wr = r["post_winrate"]
        # 初始棋盘（空盘）
        init_board = [[0] * self.board.size for _ in range(self.board.size)]
        return ReviewResponse(
            game_id=self.game_id,
            board_size=self.board.size,
            komi=self.komi,
            difficulty=self.difficulty,
            engine=self.engine.name if self.engine else None,
            human_color=COLOR_NAME[self.human_color],
            ai_color=COLOR_NAME[self.ai_color],
            initial_board=init_board,
            move_log=[
                [x, y, COLOR_NAME[c]] if (x, y) else None
                for (x, y), c in self.board.move_log
            ],
            entries=entries,
            finished=self.finished,
            score=score_chinese(self.board, self.komi).as_dict() if self.finished else None,
        )


class GameService:
    def __init__(self):
        self._games: dict[str, GameSession] = {}

    def new_game(
        self,
        board_size: int = 19,
        komi: float = 7.5,
        human_color: str = "black",
        difficulty: str = "medium",
    ) -> GameSession:
        game_id = uuid.uuid4().hex[:12]
        board = GoBoard(size=board_size)
        human = NAME_COLOR[human_color]
        ai = opponent(human)
        session = GameSession(
            game_id=game_id,
            board=board,
            komi=komi,
            human_color=human,
            ai_color=ai,
            difficulty=difficulty,
        )
        self._games[game_id] = session
        return session

    def get(self, game_id: str) -> Optional[GameSession]:
        return self._games.get(game_id)

    def review(self, game_id: str) -> Optional[ReviewResponse]:
        session = self._games.get(game_id)
        if session is None:
            return None
        return session.to_review()

    def _snapshot(self, session: GameSession) -> None:
        session.history_snapshots.append(session.board.clone())

    def play_human(
        self, game_id: str, x: Optional[int], y: Optional[int], pass_move: bool, resign: bool
    ) -> PlayResponse:
        session = self._games.get(game_id)
        if session is None:
            return PlayResponse(
                game_id=game_id, ok=False, illegal_reason="game not found",
                board=[], to_move="black", captures={"black": 0, "white": 0},
            )
        if session.finished:
            return self._state_response(session, ok=False, reason="game finished")
        if session.board.to_move() != session.human_color:
            return self._state_response(session, ok=False, reason="not your turn")

        if resign:
            session.finished = True
            return self._state_response(session, ok=True)

        self._snapshot(session)
        human_move_xy: Optional[tuple[int, int]] = None
        if pass_move:
            session.board.pass_move(session.human_color)
        else:
            if x is None or y is None:
                session.history_snapshots.pop()
                return self._state_response(session, ok=False, reason="missing coordinates")
            res = session.board.place_stone(x, y, session.human_color)
            if not res["ok"]:
                session.history_snapshots.pop()
                return self._state_response(session, ok=False, reason=res["reason"])
            human_move_xy = (x, y)

        # 记录人的走子到复盘日志
        session._append_review_entry(
            move=human_move_xy,
            color=COLOR_NAME[session.human_color],
            pre_analysis=session._pending_pre_analysis,
        )
        session._pending_pre_analysis = None

        if session.board.is_finished():
            session.finished = True
            return self._state_response(session, ok=True)

        # 关键优化：play 端点不直接做 AI 分析（耗时 5-15s 可能触发网关超时）。
        # 改为返回一个标记，让前端单独调用 /api/ai_move 获取 AI 应手。
        resp = self._state_response(session, ok=True)
        resp.ai_pending = True  # 前端需调用 ai_move 完成 AI 应手
        return resp

    def _ai_move(self, session: GameSession) -> PlayResponse:
        engine = session.engine
        try:
            analysis = engine.analyze(session.board, session.ai_color, top_k=10)
        except Exception:
            # 分析失败或超时，降级：用启发式选一步
            analysis = AnalysisResult(
                best_move=None,
                winrate=0.5,
                score_lead=None,
                candidates=[],
                engine=engine.name,
            )
            # 启发式：选第一个合法点（交给 _ordered_legal_moves 排序过的最佳点）
            moves = session.board.legal_moves(session.ai_color)
            if moves:
                analysis.best_move = moves[0]

        # AI 认输：AI 自己的胜率持续极低且已进入中盘，结束对局
        # 注意：analysis.winrate 是 AI 方视角，只有它低到阈值下才认输
        if getattr(analysis, "resign", False):
            session.finished = True
            session._append_review_entry(
                move=None,
                color=COLOR_NAME[session.ai_color],
                pre_analysis=analysis,
                post_analysis=analysis,
            )
            resp = self._state_response(session, ok=True)
            resp.ai_resigned = True
            # ai_winrate 保存 AI 自己的胜率（认输时展示给用户看的）
            resp.ai_winrate = analysis.winrate
            # 认输后没有"下一手"，winrate 不设；score_lead 保留 AI 视角
            resp.score_lead = analysis.score_lead
            return resp

        ai_move_xy: Optional[tuple[int, int]] = None
        if analysis.best_move is not None:
            session.board.place_stone(analysis.best_move[0], analysis.best_move[1], session.ai_color)
            ai_move_xy = analysis.best_move
            last_ai = MoveInfo(
                x=analysis.best_move[0], y=analysis.best_move[1],
                color=COLOR_NAME[session.ai_color],
            )
        else:
            session.board.pass_move(session.ai_color)
            last_ai = None

        # 记录 AI 走子到复盘日志（pre_analysis = AI 走子前的分析，即当前 analysis）
        session._append_review_entry(
            move=ai_move_xy,
            color=COLOR_NAME[session.ai_color],
            pre_analysis=analysis,
            post_analysis=analysis,
        )

        if session.board.is_finished():
            session.finished = True

        resp = self._state_response(session, ok=True)
        resp.ai_move = last_ai
        # ai_winrate：AI 视角的胜率（走子前 AI 评估自己的胜率）
        resp.ai_winrate = analysis.winrate
        # winrate：现在轮到玩家走，所以是玩家视角的胜率 = 1 - AI 胜率
        # 这确保前端显示"玩家胜率"时直接读 winrate 字段即可
        resp.winrate = 1.0 - analysis.winrate
        # score_lead：翻转到当前走子方（玩家）视角
        if analysis.score_lead is not None:
            resp.score_lead = -analysis.score_lead
        else:
            resp.score_lead = None
        # 候选点：翻转 winrate/score_lead 到当前走子方（玩家）视角
        resp.candidates = [
            CandidateMove(
                x=c.x, y=c.y,
                winrate=1.0 - c.winrate,
                visits=c.visits,
                score_lead=-c.score_lead if c.score_lead is not None else None,
                prior=c.prior,
            )
            for c in analysis.candidates
        ]
        return resp

    def ai_move(self, game_id: str) -> PlayResponse:
        """Trigger the AI to move when it's the AI's turn (e.g. human chose
        white and AI moves first, or after undo leaves AI to move)."""
        session = self._games.get(game_id)
        if session is None:
            return PlayResponse(
                game_id=game_id, ok=False, illegal_reason="game not found",
                board=[], to_move="black", captures={"black": 0, "white": 0},
            )
        if session.finished:
            return self._state_response(session, ok=False, reason="game finished")
        if session.board.to_move() != session.ai_color:
            return self._state_response(session, ok=False, reason="not AI's turn")
        self._snapshot(session)
        return self._ai_move(session)

    def undo(self, game_id: str) -> PlayResponse:
        session = self._games.get(game_id)
        if session is None:
            return PlayResponse(
                game_id=game_id, ok=False, illegal_reason="game not found",
                board=[], to_move="black", captures={"black": 0, "white": 0},
            )
        # Undo one human move + one AI move (if present)
        # We rely on snapshots: pop back to a state where it's human's turn
        moves_before = len(session.board.move_log)
        while session.history_snapshots:
            snap = session.history_snapshots.pop()
            session.board = snap
            if session.board.to_move() == session.human_color:
                session.finished = False
                # 同步回退复盘日志：按 move_log 减少的步数弹出
                moves_after = len(session.board.move_log)
                drop = moves_before - moves_after
                if drop > 0 and session.review_log:
                    session.review_log = session.review_log[:max(0, len(session.review_log) - drop)]
                return self._state_response(session, ok=True)
        return self._state_response(session, ok=False, reason="nothing to undo")

    def legal_moves(self, game_id: str) -> PlayResponse:
        session = self._games.get(game_id)
        if session is None:
            return PlayResponse(
                game_id=game_id, ok=False, illegal_reason="game not found",
                board=[], to_move="black", captures={"black": 0, "white": 0},
            )
        color = session.board.to_move()
        engine = session.engine
        analysis = engine.analyze(session.board, color, top_k=15) if color == session.human_color else None
        moves = session.board.legal_moves(color)
        candidates = []
        if analysis:
            cand_by_pos = {(c.x, c.y): c for c in analysis.candidates}
            for x, y in moves:
                c = cand_by_pos.get((x, y))
                if c:
                    candidates.append(
                        CandidateMove(x=x, y=y, winrate=c.winrate, visits=c.visits,
                                      score_lead=c.score_lead, prior=c.prior)
                    )
        return PlayResponse(
            game_id=game_id, ok=True,
            board=session.board.to_grid(),
            to_move=COLOR_NAME[color],
            captures={"black": session.board.captures[BLACK], "white": session.board.captures[WHITE]},
            candidates=candidates,
        )

    def analyze(self, game_id: str) -> PlayResponse:
        session = self._games.get(game_id)
        if session is None:
            return PlayResponse(
                game_id=game_id, ok=False, illegal_reason="game not found",
                board=[], to_move="black", captures={"black": 0, "white": 0},
            )
        color = session.board.to_move()
        engine = session.engine
        analysis = engine.analyze(session.board, color, top_k=15)
        # analysis.winrate 是当前走子方视角
        # 如果当前走子方是玩家：winrate == 玩家胜率（直接给前端显示），ai_winrate = None
        # 如果当前走子方是 AI：winrate 仍用当前走子方，ai_winrate 同步（但 analyze 一般在玩家回合调）
        ai_wr = analysis.winrate if color == session.ai_color else None
        return PlayResponse(
            game_id=game_id, ok=True,
            board=session.board.to_grid(),
            to_move=COLOR_NAME[color],
            captures={"black": session.board.captures[BLACK], "white": session.board.captures[WHITE]},
            winrate=analysis.winrate,
            ai_winrate=ai_wr,
            score_lead=analysis.score_lead,
            candidates=[
                CandidateMove(x=c.x, y=c.y, winrate=c.winrate, visits=c.visits,
                              score_lead=c.score_lead, prior=c.prior)
                for c in analysis.candidates
            ],
        )

    def export_sgf(self, game_id: str) -> Optional[str]:
        session = self._games.get(game_id)
        if session is None:
            return None
        return export_sgf(session.board, komi=session.komi)

    def _state_response(
        self, session: GameSession, ok: bool, reason: Optional[str] = None
    ) -> PlayResponse:
        score = None
        if session.finished:
            try:
                score = score_chinese(session.board, session.komi).as_dict()
            except Exception:
                pass
        last_move = None
        if session.board.move_log:
            mv, c = session.board.move_log[-1]
            if mv is not None:
                last_move = MoveInfo(x=mv[0], y=mv[1], color=COLOR_NAME[c])
        return PlayResponse(
            game_id=session.game_id,
            ok=ok,
            illegal_reason=reason,
            board=session.board.to_grid(),
            to_move=COLOR_NAME[session.board.to_move()],
            captures={"black": session.board.captures[BLACK], "white": session.board.captures[WHITE]},
            last_move=last_move,
            finished=session.finished,
            score=score,
        )


_service: Optional[GameService] = None


def get_game_service() -> GameService:
    global _service
    if _service is None:
        _service = GameService()
    return _service
