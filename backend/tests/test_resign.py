"""AI 认输逻辑测试。

构造典型局面，验证：
- 极端劣势下 AI 应主动认输（resign=True）
- 正常局面 AI 不应认输
- 开局阶段即使胜率波动也不应认输（避免误判）
- game_service 层正确处理认输信号，结束对局
"""
from __future__ import annotations

from app.core.board import GoBoard, BLACK, WHITE, EMPTY
from app.ai.mcts import MCTSEngine
from app.services.game_service import GameService


def _print_board(b: GoBoard) -> str:
    chars = {EMPTY: ".", BLACK: "X", WHITE: "O"}
    return "\n".join(" ".join(chars[b.get(x, y)] for x in range(b.size)) for y in range(b.size))


# ---------------------------------------------------------------------------
# 局面 1：极端劣势 - 白棋已围出大片实地，黑棋盘面数子明显落后
#
# 双方棋型完全分断（避免 rollout 时黑棋进入白空反吃）。
# 这个测试主要验证认输触发路径，对 MCTS 评估精度的验证放到中盘测试中。
# ---------------------------------------------------------------------------
def _build_loser_position() -> GoBoard:
    """构造黑方明显劣势的中盘局面。

    白棋右下大块围住 25 目实地；黑棋左上 6 目 + 中部一颗待吃孤子。
    双方棋型完全分断（避免 rollout 时黑棋进入白空反吃），
    数子落后 25 目以上。落子数约 29，测试时通过临时调低
    RESIGN_MIN_STONES 来触发认输（门槛配置另有独立单元测试）。
    """
    b = GoBoard(size=9)
    setup = [
        # 黑棋左上小角（6 目地，棋型紧凑不会被破）
        (0, 0, BLACK), (1, 0, BLACK), (2, 0, BLACK),
        (0, 1, BLACK), (1, 1, BLACK),
        (0, 2, BLACK),
        # 黑棋中部一颗孤子（即将被吃）
        (4, 4, BLACK),
        # 白棋右下大角围出实地（25 目）
        (3, 5, WHITE), (4, 5, WHITE), (5, 5, WHITE), (6, 5, WHITE),
        (3, 6, WHITE), (4, 6, WHITE), (5, 6, WHITE), (6, 6, WHITE),
        (3, 7, WHITE), (4, 7, WHITE), (5, 7, WHITE), (6, 7, WHITE),
        (3, 8, WHITE), (4, 8, WHITE), (5, 8, WHITE), (6, 8, WHITE),
        # 白棋上部封住黑棋，形成第二块实地（约 6 目）
        (0, 4, WHITE), (1, 4, WHITE), (2, 4, WHITE), (3, 4, WHITE),
        # 白棋围杀黑中部孤子
        (4, 3, WHITE), (5, 4, WHITE),
    ]
    for x, y, c in setup:
        b.grid[y][x] = c
    b.ko_point = None
    b.history = [b._hash_position()]
    b._history_set = set(b.history)
    return b


def test_resign_extreme_loss():
    """直接测试认输策略：_should_resign 在正确条件下返回 True。
    analyze→resign 信号的端到端传播在 test_game_service_handles_resign 中通过 mock 验证。"""
    b = _build_loser_position()
    print("\n[认输测试] 黑方极度劣势局面：")
    print(_print_board(b))

    from app.core.scoring import score_chinese
    sc = score_chinese(b)
    print(f"数子: 黑={sc.black} 白={sc.white} 目差={sc.margin}")
    stones = sum(1 for y in range(b.size) for x in range(b.size) if b.get(x, y) != EMPTY)
    print(f"已落子数={stones}")
    assert sc.margin < -15, f"黑棋应落后 15 目以上，实际目差 {sc.margin}"
    assert stones >= 15, "局面落子数需满足测试需要"

    eng = MCTSEngine(difficulty="beginner")

    # --- (A) 胜率阈值逻辑 ---
    eng.RESIGN_MIN_STONES = 15  # 落子数条件满足
    eng.RESIGN_WINRATE = {k: 0.20 for k in eng.RESIGN_WINRATE}  # 阈值 20%

    # 胜率 0.5%（背水一战彻底失败）+ 落子数足够 = 应该认输
    assert eng._should_resign(b, BLACK, 0.005) is True
    # 胜率 1%（低于 20% 阈值） = 应该认输
    assert eng._should_resign(b, BLACK, 0.01) is True
    # 胜率 50%（均势） = 不认输
    assert eng._should_resign(b, BLACK, 0.50) is False
    # 胜率 19% = 接近阈值但仍应认输
    assert eng._should_resign(b, BLACK, 0.19) is True
    # 胜率 21% = 高于阈值，不应认输
    assert eng._should_resign(b, BLACK, 0.21) is False
    # 胜率 99%（绝对优势） = 绝对不认输
    assert eng._should_resign(b, BLACK, 0.99) is False
    print("胜率阈值逻辑 ✓")

    # --- (B) 落子数门槛逻辑 ---
    eng2 = MCTSEngine(difficulty="beginner")
    eng2.RESIGN_MIN_STONES = 50  # 高于当前局面 29 颗
    # 就算胜率阈值极度宽松到 99%，只要落子数不够 → 绝对不认
    eng2.RESIGN_WINRATE = {k: 0.99 for k in eng2.RESIGN_WINRATE}
    assert eng2._should_resign(b, BLACK, 0.001) is False, \
        "落子不足时，哪怕胜率 0.1% 也不能认输（背水一战尚未打完）"

    # 补足落子数门槛后 = 应该认输
    eng2.RESIGN_MIN_STONES = 5
    assert eng2._should_resign(b, BLACK, 0.001) is True
    print("落子数门槛逻辑（背水一战必须打完后才允许认输） ✓")

    # --- (C) 真实配置下的 smoke 测试 ---
    eng_real = MCTSEngine(difficulty="hard")
    # hard: RESIGN_WINRATE=0.005, RESIGN_MIN_STONES=80
    # 当前局面只有 29 颗 → 不够
    assert eng_real._should_resign(b, BLACK, 0.0001) is False
    print("hard 难度高门槛 smoke 测试 ✓（低落子数不认输）")


# ---------------------------------------------------------------------------
# 局面 2：正常开局，AI 不应认输
# ---------------------------------------------------------------------------
def test_no_resign_normal_game():
    b = GoBoard(size=9)
    # 几步正常开局
    for x, y, c in [(2, 2, BLACK), (6, 6, WHITE), (2, 6, BLACK), (6, 2, WHITE)]:
        b.place_stone(x, y, c)
    print("\n[认输测试] 正常开局局面：")
    print(_print_board(b))

    eng = MCTSEngine(difficulty="medium", seed=11)
    res = eng.analyze(b, BLACK, top_k=5)
    print(f"AI 胜率={res.winrate:.3f}  认输={res.resign}")

    assert res.resign is False, "正常开局不应认输"


# ---------------------------------------------------------------------------
# 局面 3：均势中盘，AI 不应认输
# ---------------------------------------------------------------------------
def test_no_resign_balanced_midgame():
    b = GoBoard(size=9)
    # 黑白各占两角，均势
    for x, y, c in [(2, 2, BLACK), (6, 6, WHITE), (2, 6, BLACK), (6, 2, WHITE),
                    (4, 4, BLACK), (4, 5, WHITE)]:
        b.place_stone(x, y, c)
    print("\n[认输测试] 均势中盘局面：")
    print(_print_board(b))

    eng = MCTSEngine(difficulty="medium", seed=42)
    res = eng.analyze(b, BLACK, top_k=5)
    print(f"AI 胜率={res.winrate:.3f}  认输={res.resign}")

    assert res.resign is False, "均势局面不应认输"


# ---------------------------------------------------------------------------
# 局面 4：硬难度不轻易认输（阈值更低）
# ---------------------------------------------------------------------------
def test_hard_difficulty_resists_resign():
    """hard 难度认输阈值 0.005 比 beginner 0.03 更严，
    同样劣势下应更难认输。这里只验证阈值配置正确。"""
    eng_easy = MCTSEngine(difficulty="beginner")
    eng_hard = MCTSEngine(difficulty="hard")
    # 2026-08-19 "背水一战失败才认输"最终值
    assert eng_easy.RESIGN_WINRATE["beginner"] == 0.03
    assert eng_hard.RESIGN_WINRATE["hard"] == 0.005
    assert eng_easy.RESIGN_MIN_STONES == 80
    # 验证越难的档位阈值越低
    assert (eng_hard.RESIGN_WINRATE["hard"]
            < eng_hard.RESIGN_WINRATE["medium"]
            < eng_hard.RESIGN_WINRATE["easy"]
            < eng_hard.RESIGN_WINRATE["beginner"]), \
        "难度越高认输阈值应越低（越难认输）"


# ---------------------------------------------------------------------------
# 局面 5：game_service 层正确处理认输信号
# ---------------------------------------------------------------------------
def test_game_service_handles_resign():
    """验证 game_service 正确处理 engine.analyze 返回的 resign=True 信号：
    结束对局、返回 ai_resigned=True、正确设置 finished。
    采用 monkeypatch 注入分析结果，避免依赖 MCTS 评估的实际精度。"""
    from app.ai.base import AnalysisResult, MoveEvaluation

    svc = GameService()
    # 人类执白，AI 执黑；任意难度均可
    session = svc.new_game(board_size=9, komi=7.5, human_color="white", difficulty="beginner")
    # 手动放置至少一个非空落子让 to_move 判断不依赖默认值
    session.board.place_stone(2, 2, WHITE)
    session.board.place_stone(6, 6, BLACK)
    # 确保轮到 AI (BLACK) 走
    if session.board.to_move() != session.ai_color:
        session.board.pass_move(session.board.to_move())
    assert session.board.to_move() == session.ai_color, "必须轮到 AI 走"

    # Mock engine.analyze 返回一个明确的认输信号
    def mock_analyze(*args, **kwargs):
        return AnalysisResult(
            best_move=None,  # 认输时 best_move=None
            winrate=0.003,   # AI 胜率 0.3%（背水一战失败）
            score_lead=-35.0,
            candidates=[],
            engine="mcts",
            resign=True,     # ← 关键信号
        )
    original_analyze = session.engine.analyze
    session.engine.analyze = mock_analyze
    try:
        print("\n[认输测试] game_service 处理认输信号：")
        print(f"AI color={session.ai_color}  to_move={session.board.to_move()}")
        resp = svc.ai_move(session.game_id)
        print(f"ok={resp.ok}  finished={resp.finished}  ai_resigned={resp.ai_resigned}")
        print(f"ai_winrate={resp.ai_winrate}  score_lead={resp.score_lead}")

        assert resp.ok, "响应 ok 应为 True"
        assert resp.finished, "认输后对局应结束 (finished=True)"
        assert resp.ai_resigned, "响应应包含 ai_resigned=True"
        # AI 认输时，ai_winrate 应该非常低
        assert resp.ai_winrate is not None and resp.ai_winrate < 0.01, \
            f"认输场景 ai_winrate 应接近 0，实际 {resp.ai_winrate}"
        # finished 后 session.finished 也应为 True
        assert session.finished is True, "session.finished 应被标记"
    finally:
        session.engine.analyze = original_analyze


if __name__ == "__main__":
    print("=" * 60)
    print("AI 认输逻辑测试")
    print("=" * 60)
    test_resign_extreme_loss()
    print()
    test_no_resign_normal_game()
    print()
    test_no_resign_balanced_midgame()
    print()
    test_hard_difficulty_resists_resign()
    print()
    test_game_service_handles_resign()
    print("\n" + "=" * 60)
    print("全部测试通过")
    print("=" * 60)
