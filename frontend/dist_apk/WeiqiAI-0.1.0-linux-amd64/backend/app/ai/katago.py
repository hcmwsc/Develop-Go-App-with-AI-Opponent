"""KataGo analysis adapter.

KataGo exposes an analysis engine that consumes a JSON stream of analysis
requests on stdin and emits a JSON stream of results on stdout. We spawn it
as a long-lived subprocess and feed requests.

If KataGo is not configured (binary/model missing), ``is_available()`` returns
False and the manager will fall back to MCTS.

Reference: https://github.com/lightvector/KataGo/blob/master/docs/Analysis_Engine.md
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from queue import Queue, Empty
from typing import Optional

from ..config import settings
from ..core.board import GoBoard, BLACK, WHITE, EMPTY, Color, opponent
from .base import AIEngine, AnalysisResult, MoveEvaluation


class KataGoEngine(AIEngine):
    name = "katago"

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._responses: dict[str, Queue] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._started = False

    def is_available(self) -> bool:
        return bool(
            settings.katago_binary
            and settings.katago_model
            and settings.katago_config
            and os.path.exists(settings.katago_binary)
            and os.path.exists(settings.katago_model)
            and os.path.exists(settings.katago_config)
        )

    def _ensure_started(self) -> bool:
        if self._started:
            return True
        if not self.is_available():
            return False
        try:
            self._proc = subprocess.Popen(
                [
                    settings.katago_binary,
                    "analysis",
                    "-config",
                    settings.katago_config,
                    "-model",
                    settings.katago_model,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            return False
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()
        self._started = True
        return True

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            req_id = msg.get("id")
            if req_id is None:
                continue
            with self._lock:
                q = self._responses.get(req_id)
            if q is not None:
                q.put(msg)

    def analyze(self, board: GoBoard, color: Color, top_k: int = 10) -> AnalysisResult:
        if not self._ensure_started():
            raise RuntimeError("KataGo not available; configure KATAGO_* env vars")

        moves = []
        for mv, c in board.move_log:
            if mv is None:
                moves.append({"play": "pass"})
            else:
                x, y = mv
                player = "B" if c == BLACK else "W"
                coord = "abcdefghjklmnopqrstuvwxyz"[x] + "abcdefghjklmnopqrstuvwxyz"[y]
                moves.append({"x": x, "y": y, "color": player})
        # Skip 'I' in standard SGF-style coords (KataGo uses A-H, J-T for 19x19)
        # KataGo's analysis API accepts (x, y) tuples directly with color B/W.
        request = {
            "id": str(uuid.uuid4()),
            "moves": moves,
            "initialStones": [],
            "rules": "chinese",
            "komi": 7.5,
            "boardXSize": board.size,
            "boardYSize": board.size,
            "analyzeTurns": [len(moves)],
            "maxVisits": 200,
            "includePolicy": True,
            "includeOwnership": False,
        }
        req_id = request["id"]
        q: Queue = Queue()
        with self._lock:
            self._responses[req_id] = q
        try:
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write(json.dumps(request) + "\n")
            self._proc.stdin.flush()
            try:
                msg = q.get(timeout=10.0)
            except Empty:
                return AnalysisResult(
                    best_move=None,
                    winrate=0.5,
                    score_lead=None,
                    candidates=[],
                    engine=self.name,
                )
        finally:
            with self._lock:
                self._responses.pop(req_id, None)

        turn_info = msg.get("turnInfo", [{}])[0]
        move_infos = msg.get("moveInfos", [])
        root_info = msg.get("rootInfo", {})
        wr = root_info.get("winrate", 0.5)
        if color == WHITE:
            wr = 1.0 - wr  # KataGo reports from black's perspective
        score_lead = root_info.get("scoreLead")
        if score_lead is not None and color == WHITE:
            score_lead = -score_lead

        candidates: list[MoveEvaluation] = []
        for mi in move_infos[:top_k]:
            x = mi.get("move", "")[:1]
            # parse move coords: KataGo uses uppercase letters skipping 'I'
            try:
                mv = mi.get("move", "")
                col_char, row_char = mv[0], mv[1]
                mx = "abcdefghjklmnopqrstuvwxyz".index(col_char.lower())
                my = "abcdefghjklmnopqrstuvwxyz".index(row_char.lower())
            except (IndexError, ValueError):
                continue
            cand_wr = mi.get("winrate", 0.5)
            if color == WHITE:
                cand_wr = 1.0 - cand_wr
            candidates.append(
                MoveEvaluation(
                    x=mx,
                    y=my,
                    winrate=cand_wr,
                    visits=int(mi.get("visits", 0)),
                    score_lead=mi.get("scoreLead"),
                    prior=mi.get("prior"),
                )
            )
        best = None
        if move_infos:
            best_mi = move_infos[0]
            mv = best_mi.get("move", "")
            if len(mv) >= 2:
                try:
                    mx = "abcdefghjklmnopqrstuvwxyz".index(mv[0].lower())
                    my = "abcdefghjklmnopqrstuvwxyz".index(mv[1].lower())
                    best = (mx, my)
                except ValueError:
                    best = None
        return AnalysisResult(
            best_move=best,
            winrate=wr,
            score_lead=score_lead,
            candidates=candidates,
            engine=self.name,
        )

    def shutdown(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
            self._proc = None
            self._started = False
