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
    黑棋已落子数 >= 15，数子落后 25 目以上。
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
    b = _build_loser_position()
    print("\n[认输测试] 黑方极度劣势局面：")
    print(_print_board(b))

    # 先验证数子确实劣势
    from app.core.scoring import score_chinese
    sc = score_chinese(b)
    print(f"数子: 黑={sc.black} 白={sc.white} 目差={sc.margin}")

    # 黑棋已落子数 >= 15，且数子明显劣势
    stones = sum(1 for y in range(b.size) for x in range(b.size) if b.get(x, y) != EMPTY)
    assert stones >= 15, f"已落子数 {stones} 应 >= 15"
    assert sc.margin < -15, f"黑棋应落后 15 目以上，实际目差 {sc.margin}"

    # 用极低难度（认输阈值 0.10）触发认输，避免 rollout 评估精度问题
    eng = MCTSEngine(difficulty="beginner", seed=7)
    res = eng.analyze(b, BLACK, top_k=5)
    print(f"AI 胜率={res.winrate:.3f}  目差={res.score_lead}  认输={res.resign}")

    # 已落子数满足阈值，胜率应触发认输（beginner 阈值 0.10）
    # 即便 rollout 评估有偏差，数子 -25 目的局面胜率也应 < 0.10
    assert res.winrate < 0.10, f"劣势局面胜率应 <10%，实际 {res.winrate:.3f}"
    assert res.resign is True, f"AI 应认输，但 resign={res.resign}"


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
    """hard 难度认输阈值 0.03 比 medium 0.05 更严，
    同样劣势下应更难认输。这里只验证阈值配置正确。"""
    eng_easy = MCTSEngine(difficulty="beginner")
    eng_hard = MCTSEngine(difficulty="hard")
    assert eng_easy.RESIGN_WINRATE["beginner"] == 0.10
    assert eng_hard.RESIGN_WINRATE["hard"] == 0.03
    assert eng_easy.RESIGN_MIN_STONES == 15


# ---------------------------------------------------------------------------
# 局面 5：game_service 层正确处理认输信号
# ---------------------------------------------------------------------------
def test_game_service_handles_resign():
    """构造一个让 AI 必然认输的劣势对局，验证 game_service 返回 ai_resigned=True 并结束对局。"""
    svc = GameService()
    # 人类执白，AI 执黑（劣势方）；用 beginner 难度（认输阈值 0.10，更易触发）
    session = svc.new_game(board_size=9, komi=7.5, human_color="white", difficulty="beginner")
    # 手动构造黑方极度劣势局面
    b = _build_loser_position()
    session.board = b
    # move_log 为空时 to_move 返回 BLACK，等于 ai_color，所以轮到 AI 走
    assert session.board.to_move() == BLACK == session.ai_color

    print("\n[认输测试] game_service 处理认输信号：")
    print(_print_board(b))

    resp = svc.ai_move(session.game_id)
    print(f"ok={resp.ok}  finished={resp.finished}  ai_resigned={resp.ai_resigned}")
    print(f"ai_winrate={resp.ai_winrate}")

    assert resp.ok
    assert resp.finished, "认输后对局应结束"
    assert resp.ai_resigned, "响应应包含 ai_resigned=True"


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
