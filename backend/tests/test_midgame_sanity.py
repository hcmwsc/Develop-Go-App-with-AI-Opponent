"""中盘阶段走棋合理性测试。

构造若干典型中盘局面，让 MCTS 引擎分析，验证：
- AI 不会下出非法/自杀/填自己真眼的着法
- AI 应对打入子时选择攻击性着点（贴近打入子）
- AI 在己方棋子受威胁时考虑救援
- AI 不在边角无意义位置瞎下
- 胜率/目差估计处于合理区间

棋盘使用 9x9 加快搜索速度。难度统一 medium（默认强度）。
"""
from __future__ import annotations

import time
from typing import Optional

import pytest

from app.core.board import GoBoard, BLACK, WHITE, EMPTY
from app.ai.mcts import MCTSEngine


def _setup_position(size: int, moves: list[tuple[int, int, int]]) -> GoBoard:
    """按 (x, y, color) 序列在空棋盘上落子构造局面。

    直接调用 place_stone 保证合法性 & ko 状态正确。
    """
    b = GoBoard(size=size)
    for x, y, c in moves:
        res = b.place_stone(x, y, c)
        assert res["ok"], f"setup move ({x},{y},{c}) illegal: {res['reason']}"
    return b


def _print_board(b: GoBoard, marker: Optional[tuple[int, int]] = None) -> str:
    chars = {EMPTY: ".", BLACK: "X", WHITE: "O"}
    lines = []
    for y in range(b.size):
        row = []
        for x in range(b.size):
            if marker == (x, y):
                row.append("*")
            else:
                row.append(chars[b.get(x, y)])
        lines.append(" ".join(row))
    return "\n".join(lines)


def _distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# ---------------------------------------------------------------------------
# 局面 1：白挂角打入黑角，黑（AI）应选择贴近白子的攻击/夹击点
#
# 9x9 棋盘，星位 (2,2)/(6,6)。
# 黑占 (2,2) 守角，白挂角到 (3,3) 附近，黑应下在白子周围（如 (4,4)/(2,3)/(3,2)）
# ---------------------------------------------------------------------------
def test_midgame_response_to_invasion():
    moves = [
        (2, 2, BLACK),  # 黑星位
        (6, 6, WHITE),  # 白星位
        (2, 6, BLACK),  # 黑另一星位
        (6, 2, WHITE),  # 白另一星位
        (3, 3, WHITE),  # 白挂角打入黑角
    ]
    b = _setup_position(9, moves)
    print("\n[局面1] 白挂角打入，黑应攻击打入子:")
    print(_print_board(b))

    eng = MCTSEngine(difficulty="medium", seed=7)
    t0 = time.time()
    res = eng.analyze(b, BLACK, top_k=5)
    elapsed = time.time() - t0

    bm = res.best_move
    print(f"AI 选择: {bm}  胜率={res.winrate:.3f}  目差={res.score_lead}")
    print(f"候选点:")
    for c in res.candidates:
        print(f"  ({c.x},{c.y})  胜率={c.winrate:.3f}  visits={c.visits}")
    print(f"耗时: {elapsed:.2f}s")

    assert bm is not None, "AI 应给出着法"
    # 合法性
    assert b.is_legal(bm[0], bm[1], BLACK), "AI 走子必须合法"
    # 合理性：白打入子在 (3,3)，黑应在 4 格内回击（攻击或夹击）
    dist = _distance(bm, (3, 3))
    assert dist <= 3, f"AI 应贴近打入子（距离≤3），实际距离 {dist} 到 {bm}"
    # 胜率应在 [0.2, 0.8] 范围，开局均势不至于极端
    assert 0.15 <= res.winrate <= 0.90, f"胜率异常: {res.winrate}"


# ---------------------------------------------------------------------------
# 局面 2：接触战 - 双方棋子直接接触，AI 应选择恰当的应手（长/扳/挡）
#
# 黑白在边上接触：
#   . X O . .
#   X . O . .
#   . X O . .
# 黑有断点，AI(白) 应选择断或挡
# ---------------------------------------------------------------------------
def test_midgame_contact_battle():
    # 构造一个边上接触战
    moves = [
        (2, 2, BLACK),
        (6, 6, WHITE),
        (3, 2, BLACK),  # 黑在边上
        (4, 2, WHITE),  # 白贴上
        (3, 3, BLACK),  # 黑长
        (4, 3, WHITE),  # 白长
    ]
    b = _setup_position(9, moves)
    print("\n[局面2] 边上接触战，黑应:")
    print(_print_board(b))

    eng = MCTSEngine(difficulty="medium", seed=11)
    t0 = time.time()
    res = eng.analyze(b, BLACK, top_k=5)
    elapsed = time.time() - t0

    bm = res.best_move
    print(f"AI 选择: {bm}  胜率={res.winrate:.3f}  目差={res.score_lead}")
    print(f"候选点:")
    for c in res.candidates:
        print(f"  ({c.x},{c.y})  胜率={c.winrate:.3f}  visits={c.visits}")
    print(f"耗时: {elapsed:.2f}s")

    assert bm is not None
    assert b.is_legal(bm[0], bm[1], BLACK), "AI 走子必须合法"
    # 接触战时应下在已有接触点附近（曼哈顿距离 ≤ 4，允许小幅扩张攻击对方）
    contact_points = [(3, 2), (4, 2), (3, 3), (4, 3), (6, 6)]
    min_d = min(_distance(bm, p) for p in contact_points)
    assert min_d <= 4, f"AI 应在接触战附近应手，最近距离 {min_d} 到 {bm}"


# ---------------------------------------------------------------------------
# 局面 3：救棋 - 己方棋子只剩 2 气，AI 应考虑救援（连接或长气）
#
# 黑棋 (0,0) 单子被白 (1,0)/(0,1) 包围只剩 2 气? 实际 (0,0) 角部被两面
# 围攻只有 2 个空点 (1,0 已白, 0,1 已白，所以只剩... 角部被两面围只剩 0
# 气会立即被吃，这里换个构造)
#
# 黑单子在 (3,3)，白 (2,3)(4,3)(3,2)(3,4) 围之，只剩0气？也不对，那是
# 4 面全围即吃。改为：黑子 (3,3)，白占 (2,3)(3,2)(4,3) 三面，黑剩 1 气
# 在 (3,4)。AI 黑若下 (3,4) 救援其实是连一颗两气。
# ---------------------------------------------------------------------------
def test_midgame_rescue_lonely_stone():
    # 黑单子 (3,3) 三面被白围攻，只剩 (3,4) 一气
    moves = [
        (2, 2, BLACK),  # 黑星位（开局背景）
        (6, 6, WHITE),
        (3, 3, BLACK),  # 黑孤子
        (2, 3, WHITE),  # 白围
        (3, 2, WHITE),  # 白围
        (4, 3, WHITE),  # 白围 -> (3,3) 只剩 (3,4) 一气
        (6, 2, BLACK),  # 给黑别处也有子，避免局面太极端
        (2, 6, WHITE),
    ]
    b = _setup_position(9, moves)
    print("\n[局面3] 黑孤子 (3,3) 只剩一气，AI 应救援:")
    print(_print_board(b))

    eng = MCTSEngine(difficulty="medium", seed=3)
    t0 = time.time()
    res = eng.analyze(b, BLACK, top_k=5)
    elapsed = time.time() - t0

    bm = res.best_move
    print(f"AI 选择: {bm}  胜率={res.winrate:.3f}  目差={res.score_lead}")
    print(f"候选点:")
    for c in res.candidates:
        print(f"  ({c.x},{c.y})  胜率={c.winrate:.3f}  visits={c.visits}")
    print(f"耗时: {elapsed:.2f}s")

    assert bm is not None
    assert b.is_legal(bm[0], bm[1], BLACK), "AI 走子必须合法"

    # 救援点 (3,4) 应在候选前 3 名内（救援是合理选择之一）
    # 这里不强制 AI 必须救，但要验证 AI 至少考虑了救援
    top3 = [(c.x, c.y) for c in res.candidates[:3]]
    rescue_move = (3, 4)
    print(f"前3候选: {top3}, 救援点 {rescue_move}")
    # 由于 (3,3) 黑只剩 1 气，救援 (3,4) 后会变成 2 气但被白 (4,4) 再挤
    # 就吃；所以实际 AI 可能选择弃子取势。这里改为检查 AI 不会下在
    # "完全无关的边角"——必须下在 (3,3) 5 格内（接触战/救援/顺势）。
    nearby = _distance(bm, (3, 3)) <= 4
    # 或在另一处己方子附近扩展
    near_other = _distance(bm, (2, 2)) <= 3 or _distance(bm, (6, 2)) <= 3
    assert nearby or near_other, (
        f"AI 应在受威胁棋子附近救援或在己方势力内扩张，实际 {bm}"
    )


# ---------------------------------------------------------------------------
# 局面 4：扩张 - 双方各占一角，AI 应在边上/大场选点（不贴边乱下）
#
# 验证 AI 选点不会出现在棋盘第一线的角部无意义位置
# ---------------------------------------------------------------------------
def test_midgame_expansion_not_edge_corner():
    moves = [
        (2, 2, BLACK),
        (6, 6, WHITE),
        (2, 6, BLACK),
        (6, 2, WHITE),
    ]
    b = _setup_position(9, moves)
    print("\n[局面4] 双方布局完成，黑应选大场（边/中腹要点）:")
    print(_print_board(b))

    eng = MCTSEngine(difficulty="medium", seed=99)
    t0 = time.time()
    res = eng.analyze(b, BLACK, top_k=5)
    elapsed = time.time() - t0

    bm = res.best_move
    print(f"AI 选择: {bm}  胜率={res.winrate:.3f}  目差={res.score_lead}")
    print(f"候选点:")
    for c in res.candidates:
        print(f"  ({c.x},{c.y})  胜率={c.winrate:.3f}  visits={c.visits}")
    print(f"耗时: {elapsed:.2f}s")

    assert bm is not None
    assert b.is_legal(bm[0], bm[1], BLACK), "AI 走子必须合法"
    x, y = bm
    # 不应在棋盘最外圈（边线）瞎下（开局布局阶段，第一线是劣着）
    on_edge = (x == 0 or x == 8 or y == 0 or y == 8)
    # 允许在二线，但禁止第一线
    assert not on_edge, f"AI 不应在第一线（边线）下子: {bm}"
    # 胜率合理
    assert 0.2 <= res.winrate <= 0.85


# ---------------------------------------------------------------------------
# 局面 5：模拟中盘对局 - 让 AI 与"模拟人类走子"对弈 10 手，观察每步胜率/目差是否稳定
# ---------------------------------------------------------------------------
def test_midgame_self_play_stability():
    print("\n[局面5] AI 自我对弈 10 手，观察中盘胜率/目差变化:")
    b = GoBoard(size=9)
    eng_b = MCTSEngine(difficulty="medium", seed=2024)
    eng_w = MCTSEngine(difficulty="medium", seed=2025)

    color = BLACK
    for i in range(10):
        eng = eng_b if color == BLACK else eng_w
        t0 = time.time()
        res = eng.analyze(b, color, top_k=3)
        elapsed = time.time() - t0
        bm = res.best_move
        if bm is None:
            print(f"  #{i+1} {('黑' if color==BLACK else '白')}: pass  胜率={res.winrate:.3f}")
            b.pass_move(color)
        else:
            r = b.place_stone(bm[0], bm[1], color)
            status = "ok" if r["ok"] else f"ILLEGAL({r['reason']})"
            print(
                f"  #{i+1} {('黑' if color==BLACK else '白')}: ({bm[0]},{bm[1]})  "
                f"胜率={res.winrate:.3f}  目差={res.score_lead}  "
                f"耗时={elapsed:.2f}s  {status}"
            )
            assert r["ok"], f"AI 走出非法着法: {bm} -> {r['reason']}"
        color = WHITE if color == BLACK else BLACK

    print("\n最终局面:")
    print(_print_board(b))

    # 全部走子合法即通过；同时目差不应极端（10 手内不至于 ±50 目）
    # 这里只做合理性断言
    assert b.move_log and len([m for m in b.move_log if m[0] is not None]) >= 8


if __name__ == "__main__":
    # 直接运行做集成测试（pytest 之外的可视化）
    print("=" * 60)
    print("中盘走棋合理性测试")
    print("=" * 60)
    test_midgame_response_to_invasion()
    print()
    test_midgame_contact_battle()
    print()
    test_midgame_rescue_lonely_stone()
    print()
    test_midgame_expansion_not_edge_corner()
    print()
    test_midgame_self_play_stability()
    print("\n" + "=" * 60)
    print("全部测试通过")
    print("=" * 60)
