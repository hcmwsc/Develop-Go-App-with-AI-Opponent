// Shared types mirroring backend Pydantic schemas.

export type Color = 0 | 1 | 2; // 0 empty, 1 black, 2 white
export type Player = "black" | "white";

export interface Point {
  x: number;
  y: number;
}

export interface CandidateMove {
  x: number;
  y: number;
  winrate: number; // 0..1 from perspective of player to move
  visits?: number;
  score_lead?: number | null;
  prior?: number | null;
}

export interface MoveInfo {
  x: number;
  y: number;
  color: Player;
}

export interface ScoreResult {
  black: number;
  white: number;
  komi: number;
  winner: "black" | "white" | "draw";
  margin: number;
  territory_black: number;
  territory_white: number;
}

export interface GameState {
  game_id: string;
  board: number[][];
  board_size: number;
  komi: number;
  to_move: Player;
  captures: { black: number; white: number };
  move_log: (MoveInfo | null)[];
  finished: boolean;
  score?: ScoreResult | null;
  difficulty?: string | null;
  engine?: string | null;
}

export interface PlayResponse {
  game_id: string;
  ok: boolean;
  illegal_reason?: string | null;
  board: number[][];
  to_move: Player;
  captures: { black: number; white: number };
  last_move?: MoveInfo | null;
  ai_move?: MoveInfo | null;
  // winrate: 当前走子方 (to_move) 视角的胜率，前端显示玩家胜率时直接用
  winrate?: number | null;
  // ai_winrate: AI 方视角的胜率，仅 AI 相关响应（走子/认输）时有值
  ai_winrate?: number | null;
  score_lead?: number | null;
  candidates: CandidateMove[];
  finished: boolean;
  ai_resigned?: boolean;
  ai_pending?: boolean;
  score?: ScoreResult | null;
}

export type Difficulty = "beginner" | "easy" | "medium" | "hard";

export interface NewGameRequest {
  board_size: number;
  komi: number;
  player_color: Player;
  ai_engine?: "auto" | "mcts" | "katago";
  ai_difficulty?: Difficulty;
}

export interface EngineStatus {
  engine: string;
  katago_available: boolean;
  mcts_simulations: number;
  difficulties: string[];
}

export interface ReviewCandidate {
  x: number;
  y: number;
  winrate: number;
  visits?: number;
  score_lead?: number | null;
  prior?: number | null;
}

export interface ReviewEntry {
  move_number: number;
  move: number[] | null; // [x, y] or null for pass
  color: Player;
  pre_winrate: number | null;
  post_winrate: number | null;
  pre_score_lead: number | null;
  post_score_lead: number | null;
  best_move: number[] | null;
  candidates: ReviewCandidate[];
  is_key_move: boolean;
}

export interface ReviewData {
  game_id: string;
  board_size: number;
  komi: number;
  difficulty: string;
  engine: string;
  human_color: Player;
  ai_color: Player;
  initial_board: number[][];
  move_log: (number[] | null)[]; // [x, y, color] or null
  entries: ReviewEntry[];
  finished: boolean;
  score: ScoreResult | null;
}
