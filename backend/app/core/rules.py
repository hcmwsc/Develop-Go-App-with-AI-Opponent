"""Rule helpers and SGF export."""
from __future__ import annotations

from typing import Optional

from .board import GoBoard, BLACK, WHITE, Color


COLOR_SGF = {BLACK: "B", WHITE: "W"}


def coord_to_sgf(x: int, y: int, size: int) -> str:
    """Convert (x, y) to SGF coordinate, e.g. (0,0) -> 'aa'. Pass -> ''."""
    if x < 0 or y < 0:
        return ""
    return chr(ord("a") + x) + chr(ord("a") + y)


def export_sgf(board: GoBoard, komi: float = 7.5, result: Optional[str] = None) -> str:
    """Serialize the move log to a minimal SGF string."""
    lines = [
        f"(;GM[1]FF[4]CA[UTF-8]",
        f"SZ[{board.size}]KM[{komi}]",
    ]
    if result:
        lines.append(f"RE[{result}]")
    for move, color in board.move_log:
        if move is None:
            lines.append(f";{COLOR_SGF[color]}[]")
        else:
            x, y = move
            lines.append(f";{COLOR_SGF[color]}[{coord_to_sgf(x, y, board.size)}]")
    lines.append(")")
    return "\n".join(lines)
