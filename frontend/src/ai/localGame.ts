// Local (in-browser/WebView) implementation of the backend game API.
// Shapes match the Pydantic schemas in backend/app/models/schemas.py exactly,
// so the React app works offline (Android APK, web preview, Electron desktop)
// without any FastAPI backend.
//
// Uses the TS port of GoBoard + MCTS we wrote (localMcts.ts).
import type {
  CandidateMove,
  Difficulty,
  EngineStatus,
  GameState,
  MoveInfo,
  NewGameRequest,
  PlayResponse,
  Player,
  ReviewCandidate,
  ReviewData,
  ReviewEntry,
  ScoreResult,
} from "../types";
import {
  BLACK,
  WHITE,
  GoBoard,
  MCTS,
  Point,
  opponent as oppColor,
  scoreChinese,
  getEngine,
} from "./localMcts";

type Color = typeof BLACK | typeof WHITE;
type Diff = Difficulty;

interface Session {
  id: string;
  size: number;
  komi: number;
  humanColor: Color;
  difficulty: Diff;
  engine: MCTS;
  board: GoBoard;
  finished: boolean;
  result: string | null;
}

const sessions = new Map<string, Session>();
let seq = 0;
const newId = (): string => `L-${Date.now().toString(36)}-${(seq++).toString(36)}`;

const toPlayer = (c: Color): Player => (c === BLACK ? "black" : "white");
const toColor = (p: Player): Color => (p === "black" ? BLACK : WHITE);

function toMoveLog(board: GoBoard): (MoveInfo | null)[] {
  return board.moveLog.map(([pt, c]) => {
    if (pt === null) return null;
    return { x: pt[0], y: pt[1], color: toPlayer(c) };
  });
}

function buildScore(board: GoBoard, komi: number): ScoreResult {
  const sc = scoreChinese(board, komi);
  return {
    black: sc.black,
    white: sc.white,
    komi: sc.komi,
    winner: sc.winner,
    margin: sc.margin,
    territory_black: sc.territoryBlack,
    territory_white: sc.territoryWhite,
  };
}

function applyFinish(s: Session): void {
  if (s.finished) return;
  if (!s.board.isFinished()) return;
  const sc = scoreChinese(s.board, s.komi);
  if (sc.winner === "draw") s.result = "Draw";
  else s.result = `${sc.winner[0].toUpperCase()}${sc.winner.slice(1)} wins by ${Math.abs(sc.margin).toFixed(1)}`;
  s.finished = true;
}

function buildGameState(s: Session, opts?: {
  winrate?: number;
  scoreLead?: number | null;
  candidates?: CandidateMove[];
  engineName?: string;
}): GameState {
  const score: ScoreResult | null = s.finished ? buildScore(s.board, s.komi) : null;
  return {
    game_id: s.id,
    board: s.board.grid.map((row) => row.slice()),
    board_size: s.size,
    komi: s.komi,
    to_move: toPlayer(s.board.toMove()),
    captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
    move_log: toMoveLog(s.board),
    finished: s.finished,
    score,
    difficulty: s.difficulty,
    engine: opts?.engineName ?? "mcts-js",
    // Backend also stores winrate/candidates under separate PlayResponse
    // fields; we still put them here for callers that inspect the state.
    winrate: opts?.winrate,
    candidates: opts?.candidates ?? [],
  } as GameState;
}

/**
 * Run analysis and produce:
 *  - winrate: from POV of `analyzeColor` (defaults to current to_move)
 *  - score_lead: from POV of `analyzeColor`
 *  - candidates: winrate from POV of `analyzeColor`
 */
function analyze(
  s: Session,
  analyzeColor?: Color,
): {
  winrate: number;
  scoreLead: number | null;
  candidates: CandidateMove[];
  bestMove: Point | null;
  engineName: string;
  resign: boolean;
} {
  const color = analyzeColor ?? s.board.toMove();
  const r = s.engine.analyze(s.board, color);
  const candidates: CandidateMove[] = r.candidates.map((c) => ({
    x: c.x,
    y: c.y,
    winrate: c.winrate,
    visits: c.visits,
    score_lead: c.scoreLead ?? null,
  }));
  return {
    winrate: r.winrate,
    scoreLead: r.scoreLead,
    candidates,
    bestMove: r.bestMove,
    engineName: r.engine,
    resign: r.resign,
  };
}

/**
 * Given a current analysis (from POV of color `forColor`), compute the
 * equivalent "AI winrate" (from POV of AI color) for the PlayResponse.ai_winrate field.
 */
function aiWinrateFromAnalysis(
  s: Session,
  analysisWinrate: number,
  analysisColor: Color,
): number {
  const aiColor = oppColor(s.humanColor);
  return analysisColor === aiColor ? analysisWinrate : 1 - analysisWinrate;
}

export const localGame = {
  health(): { status: string; version: string; local: true } {
    return { status: "ok", version: "mcts-js-0.1", local: true };
  },

  engineStatus(): EngineStatus {
    return {
      engine: "mcts-js (内置本地 AI，离线可用)",
      katago_available: false,
      mcts_simulations: 6000,
      difficulties: ["beginner", "easy", "medium", "hard"],
    };
  },

  newGame(req: NewGameRequest): GameState {
    const size = req.board_size ?? 19;
    const komi = req.komi ?? 7.5;
    const humanColor = toColor(req.player_color ?? "black");
    const difficulty: Diff = (req.ai_difficulty ?? "medium") as Diff;
    const engine = getEngine(difficulty);
    const id = newId();
    const s: Session = {
      id,
      size,
      komi,
      humanColor,
      difficulty,
      engine,
      board: new GoBoard(size),
      finished: false,
      result: null,
    };
    sessions.set(id, s);

    // If AI moves first, play an AI move now so the returned state reflects it.
    let currentColor: Color = s.board.toMove();
    if (currentColor !== humanColor) {
      const analysis = analyze(s, currentColor);
      if (analysis.bestMove) {
        s.board.placeStone(analysis.bestMove[0], analysis.bestMove[1], currentColor);
      } else {
        s.board.passMove(currentColor);
      }
      applyFinish(s);
    }

    const nextAnalysis = analyze(s, s.board.toMove());
    // This analysis is from the NEXT mover POV. For GameState embedded fields we expose that,
    // which is correct because it's always the "to_move" side stats.
    return buildGameState(s, {
      winrate: nextAnalysis.winrate,
      scoreLead: nextAnalysis.scoreLead,
      candidates: nextAnalysis.candidates,
      engineName: nextAnalysis.engineName,
    });
  },

  play(
    gameId: string,
    x: number | null,
    y: number | null,
    opts?: { pass?: boolean; resign?: boolean },
  ): PlayResponse {
    const s = sessions.get(gameId);
    if (!s) {
      return {
        game_id: gameId,
        ok: false,
        illegal_reason: "对局不存在",
        board: [],
        to_move: "black",
        captures: { black: 0, white: 0 },
        candidates: [],
        finished: true,
        score: null,
      } as PlayResponse;
    }
    if (s.finished) {
      const score = buildScore(s.board, s.komi);
      const st = s.board.toMove();
      return {
        game_id: s.id,
        ok: true,
        board: s.board.grid.map((r) => r.slice()),
        to_move: toPlayer(st),
        captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
        candidates: [],
        finished: true,
        score,
      } as PlayResponse;
    }

    const humanColor = s.humanColor;
    const aiColor = oppColor(humanColor);
    const toMove = s.board.toMove();
    if (toMove !== humanColor) {
      return {
        game_id: s.id,
        ok: false,
        illegal_reason: "不是你的回合",
        board: s.board.grid.map((r) => r.slice()),
        to_move: toPlayer(toMove),
        captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
        candidates: [],
        finished: s.finished,
        score: null,
      } as PlayResponse;
    }

    // --- human resign ---
    if (opts?.resign) {
      s.finished = true;
      s.result = `${aiColor === BLACK ? "Black" : "White"} wins by resignation`;
      const score = buildScore(s.board, s.komi);
      return {
        game_id: s.id,
        ok: true,
        board: s.board.grid.map((r) => r.slice()),
        to_move: toPlayer(s.board.toMove()),
        captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
        candidates: [],
        finished: true,
        score,
        ai_resigned: false,
      } as PlayResponse;
    }

    // --- human move ---
    const humanPass = opts?.pass || x === null || y === null;
    let lastMove: MoveInfo | null = null;
    if (humanPass) {
      s.board.passMove(humanColor);
    } else {
      const res = s.board.placeStone(x, y, humanColor);
      if (!res.ok) {
        return {
          game_id: s.id,
          ok: false,
          illegal_reason: res.reason ?? "非法走子",
          board: s.board.grid.map((r) => r.slice()),
          to_move: toPlayer(toMove),
          captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
          candidates: [],
          finished: s.finished,
          score: null,
        } as PlayResponse;
      }
      lastMove = { x, y, color: toPlayer(humanColor) };
    }
    applyFinish(s);

    // --- AI move ---
    let aiMove: MoveInfo | null = null;
    let aiResigned = false;
    let winrateOut: number | null = null;
    let aiWinrateOut: number | null = null;
    let scoreLeadOut: number | null = null;
    let candidatesOut: CandidateMove[] = [];
    let aiPending = false;

    if (!s.finished) {
      const aiToMove = s.board.toMove();
      // Analyze from AI POV (=> result.winrate is AI's chance to win from here)
      const analysis = analyze(s, aiToMove);
      aiWinrateOut = analysis.winrate; // AI POV
      candidatesOut = analysis.candidates;
      scoreLeadOut = analysis.scoreLead;

      if (analysis.resign) {
        s.finished = true;
        s.result = `${humanColor === BLACK ? "Black" : "White"} wins by resignation`;
        aiResigned = true;
        winrateOut = 1 - aiWinrateOut; // player POV = 1 - AI winrate
      } else if (analysis.bestMove) {
        const [mx, my] = analysis.bestMove;
        s.board.placeStone(mx, my, aiToMove);
        aiMove = { x: mx, y: my, color: toPlayer(aiColor) };
        applyFinish(s);
        if (!s.finished) {
          // Now it's human's turn again. Re-analyze so the exposed winrate is
          // from the human's POV (matching what GameState.winrate displays).
          const post = analyze(s, s.board.toMove());
          winrateOut = post.winrate; // human POV
          scoreLeadOut = post.scoreLead;
          candidatesOut = post.candidates;
        } else {
          // finished but the last move was AI, keep AI winrate as just-computed
          // and set human winrate accordingly.
          winrateOut = 1 - aiWinrateOut;
        }
      } else {
        s.board.passMove(aiToMove);
        applyFinish(s);
        winrateOut = 1 - aiWinrateOut;
      }
    } else {
      // Game ended on human pass/other → set winrate safely
      winrateOut = 0.5;
    }

    const finalScore = s.finished ? buildScore(s.board, s.komi) : null;
    return {
      game_id: s.id,
      ok: true,
      board: s.board.grid.map((r) => r.slice()),
      to_move: toPlayer(s.board.toMove()),
      captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
      last_move: lastMove,
      ai_move: aiMove,
      winrate: winrateOut,
      ai_winrate: aiWinrateOut,
      score_lead: scoreLeadOut,
      candidates: candidatesOut,
      finished: s.finished,
      ai_resigned: aiResigned,
      ai_pending: aiPending,
      score: finalScore,
    } as PlayResponse;
  },

  aiMove(gameId: string): PlayResponse {
    const s = sessions.get(gameId);
    if (!s) {
      return {
        game_id: gameId, ok: false, illegal_reason: "对局不存在",
        board: [], to_move: "black", captures: { black: 0, white: 0 },
        candidates: [], finished: true, score: null,
      } as PlayResponse;
    }
    if (s.finished) {
      const score = buildScore(s.board, s.komi);
      return {
        game_id: s.id, ok: true,
        board: s.board.grid.map((r) => r.slice()),
        to_move: toPlayer(s.board.toMove()),
        captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
        candidates: [], finished: true, score,
      } as PlayResponse;
    }
    const toMove = s.board.toMove();
    const aiColor = oppColor(s.humanColor);
    if (toMove !== aiColor) {
      // Not AI's turn → return as no-op, still ok. This mirrors the backend behavior.
      const pre = analyze(s, toMove);
      return {
        game_id: s.id, ok: true,
        board: s.board.grid.map((r) => r.slice()),
        to_move: toPlayer(toMove),
        captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
        candidates: pre.candidates, finished: s.finished, score: null,
        winrate: pre.winrate, ai_winrate: 1 - pre.winrate, score_lead: pre.scoreLead,
      } as PlayResponse;
    }

    const analysis = analyze(s, toMove);
    let aiMove: MoveInfo | null = null;
    let aiResigned = false;
    let winrateOut: number | null = null;
    let scoreLeadOut: number | null = null;
    let candidatesOut: CandidateMove[] = analysis.candidates;
    const aiWinrateOut = analysis.winrate;

    if (analysis.resign) {
      s.finished = true;
      s.result = `${s.humanColor === BLACK ? "Black" : "White"} wins by resignation`;
      aiResigned = true;
      winrateOut = 1 - aiWinrateOut;
    } else if (analysis.bestMove) {
      const [mx, my] = analysis.bestMove;
      s.board.placeStone(mx, my, toMove);
      aiMove = { x: mx, y: my, color: toPlayer(aiColor) };
      applyFinish(s);
      if (!s.finished) {
        const post = analyze(s, s.board.toMove());
        winrateOut = post.winrate;
        scoreLeadOut = post.scoreLead;
        candidatesOut = post.candidates;
      } else {
        winrateOut = 1 - aiWinrateOut;
      }
    } else {
      s.board.passMove(toMove);
      applyFinish(s);
      winrateOut = 1 - aiWinrateOut;
    }

    const finalScore = s.finished ? buildScore(s.board, s.komi) : null;
    return {
      game_id: s.id, ok: true,
      board: s.board.grid.map((r) => r.slice()),
      to_move: toPlayer(s.board.toMove()),
      captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
      ai_move: aiMove,
      winrate: winrateOut,
      ai_winrate: aiWinrateOut,
      score_lead: scoreLeadOut,
      candidates: candidatesOut,
      finished: s.finished,
      ai_resigned: aiResigned,
      score: finalScore,
    } as PlayResponse;
  },

  undo(gameId: string): PlayResponse {
    const s = sessions.get(gameId);
    if (!s) {
      return {
        game_id: gameId, ok: false, illegal_reason: "对局不存在",
        board: [], to_move: "black", captures: { black: 0, white: 0 },
        candidates: [], finished: true, score: null,
      } as PlayResponse;
    }
    // Remove last 2 moves (human + AI), or 1 if only opening move exists.
    const log = s.board.moveLog.slice();
    const removeCount = log.length >= 2 ? 2 : log.length >= 1 ? 1 : 0;
    const keep = log.slice(0, Math.max(0, log.length - removeCount));
    const fresh = new GoBoard(s.size);
    for (const [pt, c] of keep) {
      if (pt) fresh.placeStone(pt[0], pt[1], c);
      else fresh.passMove(c);
    }
    s.board = fresh;
    s.finished = false;
    s.result = null;
    const post = analyze(s, s.board.toMove());
    const aiWinrateOut = aiWinrateFromAnalysis(s, post.winrate, s.board.toMove());
    return {
      game_id: s.id, ok: true,
      board: s.board.grid.map((r) => r.slice()),
      to_move: toPlayer(s.board.toMove()),
      captures: { black: s.board.captures[BLACK], white: s.board.captures[WHITE] },
      candidates: post.candidates,
      finished: false,
      winrate: post.winrate,
      ai_winrate: aiWinrateOut,
      score_lead: post.scoreLead,
      score: null,
    } as PlayResponse;
  },

  state(gameId: string): GameState {
    const s = sessions.get(gameId);
    if (!s) throw new Error("game not found");
    const post = analyze(s, s.board.toMove());
    return buildGameState(s, {
      winrate: post.winrate,
      scoreLead: post.scoreLead,
      candidates: post.candidates,
      engineName: post.engineName,
    });
  },

  legalMoves(gameId: string): { game_id: string; to_move: Player; moves: number[][]; candidates: CandidateMove[] } {
    const s = sessions.get(gameId);
    if (!s) throw new Error("game not found");
    const tm = s.board.toMove();
    const moves = s.board.legalMoves(tm);
    const post = analyze(s, tm);
    return {
      game_id: s.id,
      to_move: toPlayer(tm),
      moves,
      candidates: post.candidates,
    };
  },

  analyze(gameId: string): {
    game_id: string;
    best_move: { x: number; y: number; color: Player } | null;
    winrate: number;
    score_lead: number | null;
    candidates: CandidateMove[];
    engine: string;
  } {
    const s = sessions.get(gameId);
    if (!s) throw new Error("game not found");
    const tm = s.board.toMove();
    const post = analyze(s, tm);
    return {
      game_id: s.id,
      best_move: post.bestMove
        ? { x: post.bestMove[0], y: post.bestMove[1], color: toPlayer(tm) }
        : null,
      winrate: post.winrate,
      score_lead: post.scoreLead,
      candidates: post.candidates,
      engine: post.engineName,
    };
  },

  sgf(gameId: string): { game_id: string; sgf: string } {
    const s = sessions.get(gameId);
    if (!s) throw new Error("game not found");
    const col = (v: number) => String.fromCharCode("a".charCodeAt(0) + v);
    let moves = "";
    for (const [pt, c] of s.board.moveLog) {
      if (pt === null) moves += `;${c === BLACK ? "B" : "W"}[]`;
      else moves += `;${c === BLACK ? "B" : "W"}[${col(pt[0])}${col(pt[1])}]`;
    }
    const diffText: Record<string, string> = {
      beginner: "Beginner", easy: "Easy", medium: "Medium", hard: "Hard",
    };
    const sgf =
      `(;GM[1]FF[4]CA[UTF-8]SZ[${s.size}]KM[${s.komi}]` +
      `PW[White]PB[Black]GN[WeiqiAI-${diffText[s.difficulty] ?? s.difficulty}-Local]` +
      moves +
      ")";
    return { game_id: s.id, sgf };
  },

  review(gameId: string): ReviewData {
    const s = sessions.get(gameId);
    if (!s) throw new Error("game not found");
    const log = s.board.moveLog.slice();
    const replay = new GoBoard(s.size);
    const reviewEngine = new MCTS(s.difficulty);

    const entries: ReviewEntry[] = [];
    const initialBoard = replay.grid.map((r) => r.slice());
    const moveLogFlat: (number[] | null)[] = [];

    // Initial entry (before any move)
    const initialA = reviewEngine.analyze(replay, replay.toMove());
    entries.push({
      move_number: 0,
      move: null,
      color: toPlayer(BLACK),
      pre_winrate: null,
      post_winrate: initialA.winrate,
      pre_score_lead: null,
      post_score_lead: initialA.scoreLead,
      best_move: initialA.bestMove ? [initialA.bestMove[0], initialA.bestMove[1]] : null,
      candidates: initialA.candidates.map((c) => ({
        x: c.x, y: c.y, winrate: c.winrate, visits: c.visits, score_lead: c.scoreLead ?? null,
      })) as ReviewCandidate[],
      is_key_move: false,
    });

    for (let i = 0; i < log.length; i++) {
      const [pt, c] = log[i];
      const tmBefore = replay.toMove();
      const preA = reviewEngine.analyze(replay, tmBefore);
      // Record pre-move winrate from POV of the mover, and the mover's best move.
      const moveArrFlat: number[] | null = pt ? [pt[0], pt[1], c] : null;
      moveLogFlat.push(moveArrFlat);
      if (pt) replay.placeStone(pt[0], pt[1], c);
      else replay.passMove(c);
      const tmAfter = replay.toMove();
      const postA = reviewEngine.analyze(replay, tmAfter);
      // Drop if winrate changed by >= 10%
      const isKey = Math.abs((postA.winrate ?? 0.5) - (1 - (preA.winrate ?? 0.5))) >= 0.1;
      entries.push({
        move_number: i + 1,
        move: pt ? [pt[0], pt[1]] : null,
        color: toPlayer(c),
        pre_winrate: preA.winrate,
        post_winrate: postA.winrate,
        pre_score_lead: preA.scoreLead,
        post_score_lead: postA.scoreLead,
        best_move: preA.bestMove ? [preA.bestMove[0], preA.bestMove[1]] : null,
        candidates: preA.candidates.map((c2) => ({
          x: c2.x, y: c2.y, winrate: c2.winrate, visits: c2.visits, score_lead: c2.scoreLead ?? null,
        })) as ReviewCandidate[],
        is_key_move: isKey,
      });
    }

    const finished = s.finished || s.board.isFinished();
    const score = s.finished || s.board.isFinished() ? buildScore(s.board, s.komi) : null;
    return {
      game_id: s.id,
      board_size: s.size,
      komi: s.komi,
      difficulty: s.difficulty,
      engine: "mcts-js",
      human_color: toPlayer(s.humanColor),
      ai_color: toPlayer(oppColor(s.humanColor)),
      initial_board: initialBoard,
      move_log: moveLogFlat,
      entries,
      finished,
      score,
    };
  },
};

// Mode selector: returns true if local AI should be used.
export function shouldUseLocalMode(userOverride?: boolean): boolean {
  if (typeof userOverride === "boolean") return userOverride;
  // localStorage flag: let user toggle it via ControlPanel.
  try {
    const forced = localStorage.getItem("weiqi_use_local_ai");
    if (forced === "1") return true;
    if (forced === "0") return false;
  } catch { /* ignore */ }
  // Capacitor / mobile WebView always prefer local mode (since backend is
  // never bundled). Android/iOS UA strings cover most devices.
  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
  if (/android|iphone|ipad|ios|harmonyos|mobile|capacitor|electron/i.test(ua)) return true;
  return false;
}

export async function remoteHealthOk(timeoutMs = 1500): Promise<boolean> {
  // Probe the backend /health. Used as fallback to auto-enable local mode
  // when the backend is unreachable (e.g. user opened HTML file without starting uvicorn).
  try {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), timeoutMs);
    const url = (await import("../config")).endpoint("/health");
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}
