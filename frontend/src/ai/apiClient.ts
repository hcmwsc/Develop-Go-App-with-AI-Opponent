// Unified API client:
//   - calls remote FastAPI backend via fetch when available (and not explicitly
//     disabled via the local-AI toggle)
//   - otherwise falls back to the pure-TypeScript implementation in localGame.ts
//     so the app (and the Android APK) works fully offline.
import { endpoint, hasBackendConfigured } from "../config";
import { localGame, remoteHealthOk, shouldUseLocalMode } from "./localGame";
import type {
  GameState,
  PlayResponse,
  NewGameRequest,
  EngineStatus,
  CandidateMove,
  ReviewData,
} from "../types";

const DEFAULT_TIMEOUT = 120_000; // 2 min; hard level may take up to ~12s per move locally

// ---------- Async transport (remote) ----------
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
    const ct = res.headers.get("content-type") ?? "";
    if (!/json/.test(ct)) {
      const txt = await res.text();
      if (/^\s*</.test(txt)) {
        throw new Error(
          "后端地址返回的是 HTML 而非 JSON，请检查「服务器设置」填写的地址是否正确（不要填浏览器访问的预览地址）",
        );
      }
      throw new Error(`${path} -> 响应不是 JSON: ${txt.slice(0, 120)}`);
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

// ---------- Mode cache (avoid re-checking health on every call) ----------
let cachedRemote: boolean | null = null;
async function useRemote(): Promise<boolean> {
  if (shouldUseLocalMode()) return false;
  // If user configured backend explicitly, trust them.
  if (hasBackendConfigured()) {
    cachedRemote = true;
    return true;
  }
  if (cachedRemote === null) {
    cachedRemote = await remoteHealthOk(1200);
  }
  return cachedRemote;
}

export function forceMode(mode: "local" | "remote"): void {
  cachedRemote = mode === "remote";
  try {
    localStorage.setItem("weiqi_use_local_ai", mode === "local" ? "1" : "0");
  } catch {
    // ignore
  }
}

export function currentModePref(): "local" | "remote" | "auto" {
  try {
    const v = localStorage.getItem("weiqi_use_local_ai");
    if (v === "1") return "local";
    if (v === "0") return "remote";
  } catch { /* ignore */ }
  return "auto";
}

// ---------- Public API surface (shape matches api.* used by App.tsx) ----------
export const api = {
  health: async (): Promise<{ status: string; version: string; local?: boolean }> => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.health());
    return getJson<{ status: string; version: string }>("/health").catch(() => {
      cachedRemote = false;
      return localGame.health();
    });
  },

  engineStatus: async (): Promise<EngineStatus> => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.engineStatus());
    return getJson<EngineStatus>("/api/engine").catch(() => {
      cachedRemote = false;
      return localGame.engineStatus();
    });
  },

  newGame: async (req: NewGameRequest): Promise<GameState> => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.newGame(req));
    return postJson<GameState>("/api/new_game", req);
  },

  play: async (
    gameId: string,
    x: number | null,
    y: number | null,
    opts?: { pass?: boolean; resign?: boolean },
  ): Promise<PlayResponse> => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.play(gameId, x, y, opts));
    return postJson<PlayResponse>("/api/play", {
      game_id: gameId,
      x,
      y,
      pass_move: opts?.pass ?? false,
      resign: opts?.resign ?? false,
    });
  },

  undo: async (gameId: string): Promise<PlayResponse> => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.undo(gameId));
    return fetch(endpoint(`/api/undo?game_id=${encodeURIComponent(gameId)}`), {
      method: "POST",
    }).then((r) => r.json() as Promise<PlayResponse>);
  },

  aiMove: async (gameId: string): Promise<PlayResponse> => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.aiMove(gameId));
    return fetch(endpoint(`/api/ai_move?game_id=${encodeURIComponent(gameId)}`), {
      method: "POST",
    }).then((r) => r.json() as Promise<PlayResponse>);
  },

  state: async (gameId: string): Promise<GameState> => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.state(gameId));
    return getJson<GameState>(`/api/state/${gameId}`);
  },

  legalMoves: async (
    gameId: string,
  ): Promise<{ game_id: string; to_move: string; moves: number[][]; candidates: CandidateMove[] }> => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.legalMoves(gameId));
    return getJson<{ game_id: string; to_move: string; moves: number[][]; candidates: CandidateMove[] }>(
      `/api/legal_moves/${gameId}`,
    );
  },

  analyze: async (gameId: string) => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.analyze(gameId));
    return getJson<{
      game_id: string;
      best_move: { x: number; y: number; color: string } | null;
      winrate: number;
      score_lead: number | null;
      candidates: CandidateMove[];
      engine: string;
    }>(`/api/analyze/${gameId}`);
  },

  sgf: async (gameId: string) => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.sgf(gameId));
    return getJson<{ game_id: string; sgf: string }>(`/api/sgf/${gameId}`);
  },

  review: async (gameId: string): Promise<ReviewData> => {
    const rem = await useRemote();
    if (!rem) return Promise.resolve(localGame.review(gameId));
    return getJson<ReviewData>(`/api/review/${gameId}`);
  },
};
