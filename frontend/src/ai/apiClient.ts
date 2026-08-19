// Backend API client. All functions return parsed JSON or throw.
import { endpoint } from "../config";
import type {
  GameState,
  PlayResponse,
  NewGameRequest,
  EngineStatus,
  CandidateMove,
  ReviewData,
} from "../types";

const DEFAULT_TIMEOUT = 60_000; // 60s，容纳 MCTS 分析

async function postJson<T>(path: string, body: unknown, timeout = DEFAULT_TIMEOUT): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(endpoint(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${path} -> ${res.status}: ${text}`);
    }
    return res.json() as Promise<T>;
  } catch (e) {
    if ((e as Error).name === "AbortError") {
      throw new Error(`${path} -> 请求超时（${timeout / 1000}s）`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

async function getJson<T>(path: string, timeout = DEFAULT_TIMEOUT): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(endpoint(path), { signal: controller.signal });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${path} -> ${res.status}: ${text}`);
    }
    return res.json() as Promise<T>;
  } catch (e) {
    if ((e as Error).name === "AbortError") {
      throw new Error(`${path} -> 请求超时（${timeout / 1000}s）`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => getJson<{ status: string; version: string }>("/health"),
  engineStatus: () => getJson<EngineStatus>("/api/engine"),

  newGame: (req: NewGameRequest) => postJson<GameState>("/api/new_game", req),

  play: (gameId: string, x: number | null, y: number | null, opts?: { pass?: boolean; resign?: boolean }) =>
    postJson<PlayResponse>("/api/play", {
      game_id: gameId,
      x,
      y,
      pass_move: opts?.pass ?? false,
      resign: opts?.resign ?? false,
    }),

  undo: (gameId: string) =>
    fetch(endpoint(`/api/undo?game_id=${encodeURIComponent(gameId)}`), {
      method: "POST",
    }).then((r) => r.json() as Promise<PlayResponse>),

  aiMove: (gameId: string) =>
    fetch(endpoint(`/api/ai_move?game_id=${encodeURIComponent(gameId)}`), {
      method: "POST",
    }).then((r) => r.json() as Promise<PlayResponse>),

  state: (gameId: string) => getJson<GameState>(`/api/state/${gameId}`),
  legalMoves: (gameId: string) =>
    getJson<{ game_id: string; to_move: string; moves: number[][]; candidates: CandidateMove[] }>(
      `/api/legal_moves/${gameId}`
    ),
  analyze: (gameId: string) =>
    getJson<{
      game_id: string;
      best_move: { x: number; y: number; color: string } | null;
      winrate: number;
      score_lead: number | null;
      candidates: CandidateMove[];
      engine: string;
    }>(`/api/analyze/${gameId}`),
  sgf: (gameId: string) =>
    getJson<{ game_id: string; sgf: string }>(`/api/sgf/${gameId}`),
  review: (gameId: string) => getJson<ReviewData>(`/api/review/${gameId}`),
};
