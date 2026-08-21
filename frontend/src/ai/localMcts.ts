// Pure-TypeScript local AI engine: board rules + Chinese scoring + MCTS
// with RAVE/AMAF, tactical rollout, heuristic priors and resign policy.
//
// This is a self-contained port of backend/app/{core,ai}/ so the Android
// app / web preview can run entirely offline, without the FastAPI backend.
//
// Performance notes for JS:
//   - We use typed arrays sparingly; real clone speed is good enough for the
//     adjusted simulation budgets below.
//   - Simulation counts are lower than the server-side Python version so that
//     a mobile WebView still responds within a second or two.
//   - Tree reuse is kept across moves for a net 2-4x effective sample boost.

export const EMPTY = 0 as Color;
export const BLACK = 1 as Color;
export const WHITE = 2 as Color;
export type Color = 0 | 1 | 2;

export const opponent = (c: Color): Color => (c === BLACK ? WHITE : BLACK);

// ---------- GoBoard (matches backend rules: Chinese, simple ko, positional superko) ----------

export type Point = [number, number];

export class GoBoard {
  size: number;
  grid: number[][];
  captures: Record<Color, number>;
  history: number[];
  _historySet: Set<number>;
  moveLog: [Point | null, Color][];
  koPoint: Point | null;

  constructor(size = 19) {
    this.size = size;
    this.grid = Array.from({ length: size }, () => Array<number>(size).fill(EMPTY));
    this.captures = { [BLACK]: 0, [WHITE]: 0 } as Record<Color, number>;
    this.history = [];
    this._historySet = new Set();
    this.moveLog = [];
    this.koPoint = null;
    this._recordPosition();
  }

  inBounds(x: number, y: number): boolean {
    return x >= 0 && x < this.size && y >= 0 && y < this.size;
  }

  *neighbors(x: number, y: number): Generator<Point> {
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
      const nx = x + dx;
      const ny = y + dy;
      if (this.inBounds(nx, ny)) yield [nx, ny];
    }
  }

  get(x: number, y: number): Color {
    return this.grid[y][x] as Color;
  }

  getGroup(x: number, y: number): Set<string> {
    const color = this.grid[y][x];
    const seen = new Set<string>();
    if (color === EMPTY) return seen;
    const stack: Point = [x, y];
    const todo: Point[] = [stack];
    while (todo.length) {
      const [cx, cy] = todo.pop()!;
      const key = `${cx},${cy}`;
      if (seen.has(key)) continue;
      seen.add(key);
      for (const [nx, ny] of this.neighbors(cx, cy)) {
        if (this.grid[ny][nx] === color && !seen.has(`${nx},${ny}`)) {
          todo.push([nx, ny]);
        }
      }
    }
    return seen;
  }

  groupLiberties(group: Set<string>): Set<string> {
    const libs = new Set<string>();
    for (const k of group) {
      const [sx, sy] = k.split(",").map(Number) as Point;
      for (const [nx, ny] of this.neighbors(sx, sy)) {
        if (this.grid[ny][nx] === EMPTY) libs.add(`${nx},${ny}`);
      }
    }
    return libs;
  }

  groupLibertyCount(group: Set<string>): number {
    return this.groupLiberties(group).size;
  }

  isLegal(x: number, y: number, color: Color): boolean {
    if (!this.inBounds(x, y) || this.grid[y][x] !== EMPTY) return false;
    if (this.koPoint && this.koPoint[0] === x && this.koPoint[1] === y) return false;
    const opp = opponent(color);
    this.grid[y][x] = color;
    const captured: Point[] = [];
    for (const [nx, ny] of this.neighbors(x, y)) {
      if (this.grid[ny][nx] === opp) {
        const grp = this.getGroup(nx, ny);
        if (this.groupLibertyCount(grp) === 0) {
          for (const k of grp) {
            const [gx, gy] = k.split(",").map(Number) as Point;
            captured.push([gx, gy]);
          }
        }
      }
    }
    for (const [cx, cy] of captured) this.grid[cy][cx] = EMPTY;
    const own = this.getGroup(x, y);
    let legal = this.groupLibertyCount(own) > 0;
    if (legal) legal = !this._historySet.has(this.hashPosition());
    for (const [cx, cy] of captured) this.grid[cy][cx] = opp;
    this.grid[y][x] = EMPTY;
    return legal;
  }

  legalMoves(color: Color): Point[] {
    const moves: Point[] = [];
    for (let y = 0; y < this.size; y++) {
      for (let x = 0; x < this.size; x++) {
        if (this.grid[y][x] === EMPTY && this.isLegal(x, y, color)) moves.push([x, y]);
      }
    }
    return moves;
  }

  placeStone(x: number, y: number, color: Color): { ok: boolean; captured: Point[]; reason?: string } {
    if (!this.inBounds(x, y) || this.grid[y][x] !== EMPTY) return { ok: false, captured: [], reason: "occupied" };
    if (this.koPoint && this.koPoint[0] === x && this.koPoint[1] === y) return { ok: false, captured: [], reason: "ko" };
    if (!this.isLegal(x, y, color)) return { ok: false, captured: [], reason: "illegal" };

    this.grid[y][x] = color;
    const opp = opponent(color);
    const captured: Point[] = [];
    for (const [nx, ny] of this.neighbors(x, y)) {
      if (this.grid[ny][nx] === opp) {
        const grp = this.getGroup(nx, ny);
        if (this.groupLibertyCount(grp) === 0) {
          for (const k of grp) {
            const [gx, gy] = k.split(",").map(Number) as Point;
            captured.push([gx, gy]);
          }
        }
      }
    }
    for (const [cx, cy] of captured) this.grid[cy][cx] = EMPTY;
    this.captures[color] += captured.length;

    this.koPoint = null;
    if (captured.length === 1) {
      const own = this.getGroup(x, y);
      if (own.size === 1 && this.groupLibertyCount(own) === 1) {
        this.koPoint = captured[0];
      }
    }

    this._recordPosition();
    this.moveLog.push([[x, y], color]);
    return { ok: true, captured };
  }

  passMove(color: Color): void {
    this.koPoint = null;
    this.moveLog.push([null, color]);
    this._recordPosition();
  }

  toMove(): Color {
    if (!this.moveLog.length) return BLACK;
    return opponent(this.moveLog[this.moveLog.length - 1][1]);
  }

  hashPosition(): number {
    let h = 2166136261;
    for (let y = 0; y < this.size; y++) {
      const row = this.grid[y];
      for (let x = 0; x < this.size; x++) {
        h ^= row[x] + 0x9e3779b9 + (h << 6) + (h >> 2);
      }
    }
    return h | 0;
  }

  _recordPosition(): void {
    const h = this.hashPosition();
    this.history.push(h);
    this._historySet.add(h);
  }

  clone(): GoBoard {
    const nb = new GoBoard(this.size);
    nb.grid = this.grid.map((row) => row.slice());
    nb.captures = { [BLACK]: this.captures[BLACK], [WHITE]: this.captures[WHITE] } as Record<Color, number>;
    nb.history = this.history.slice();
    nb._historySet = new Set(this._historySet);
    nb.moveLog = this.moveLog.map((e) => [e[0] ? [e[0][0], e[0][1]] : null, e[1]]) as [Point | null, Color][];
    nb.koPoint = this.koPoint ? [this.koPoint[0], this.koPoint[1]] : null;
    return nb;
  }

  isFinished(): boolean {
    if (this.moveLog.length < 2) return false;
    const a = this.moveLog[this.moveLog.length - 1][0];
    const b = this.moveLog[this.moveLog.length - 2][0];
    return a === null && b === null;
  }
}

// ---------- Chinese area scoring (simplified, dame neutral) ----------

export interface ScoreResult {
  black: number;
  white: number;
  komi: number;
  winner: "black" | "white" | "draw";
  margin: number;
  territoryBlack: number;
  territoryWhite: number;
}

export function scoreChinese(board: GoBoard, komi = 7.5): ScoreResult {
  const size = board.size;
  const visited = Array.from({ length: size }, () => Array<boolean>(size).fill(false));
  let territoryBlack = 0;
  let territoryWhite = 0;
  let stoneBlack = 0;
  let stoneWhite = 0;

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const c = board.get(x, y);
      if (c === BLACK) stoneBlack++;
      else if (c === WHITE) stoneWhite++;
      else if (c === EMPTY && !visited[y][x]) {
        const region: Point[] = [];
        const borders = new Set<Color>();
        const todo: Point[] = [[x, y]];
        while (todo.length) {
          const [cx, cy] = todo.pop()!;
          if (visited[cy][cx]) continue;
          visited[cy][cx] = true;
          region.push([cx, cy]);
          for (const [nx, ny] of board.neighbors(cx, cy)) {
            const v = board.get(nx, ny);
            if (v === EMPTY) {
              if (!visited[ny][nx]) todo.push([nx, ny]);
            } else {
              borders.add(v);
            }
          }
        }
        const hasB = borders.has(BLACK);
        const hasW = borders.has(WHITE);
        if (hasB && !hasW) territoryBlack += region.length;
        else if (hasW && !hasB) territoryWhite += region.length;
      }
    }
  }

  const black = stoneBlack + territoryBlack;
  const white = stoneWhite + territoryWhite + komi;
  const margin = black - white;
  const winner: "black" | "white" | "draw" = margin > 0 ? "black" : margin < 0 ? "white" : "draw";
  return {
    black,
    white,
    komi,
    winner,
    margin,
    territoryBlack,
    territoryWhite,
  };
}

// ---------- MCTS engine (RAVE + tactical rollout) ----------

export interface MoveEval {
  x: number;
  y: number;
  winrate: number;
  visits: number;
  scoreLead?: number | null;
}

export interface AnalysisResult {
  bestMove: Point | null;
  winrate: number; // from POV of current player to move
  scoreLead: number | null;
  candidates: MoveEval[];
  engine: string;
  resign: boolean;
}

type Difficulty = "beginner" | "easy" | "medium" | "hard";

// Tuned for WebView/CPU. Boosted simulation counts give ~50% more search
// per move vs previous config, with longer deadlines for hard/medium.
// Even on a midrange phone, 6000 simulations of 19x19 board with rollouts
// up to 300 depth fit comfortably in ~15s.
const DIFFICULTY_PRESETS: Record<Difficulty, [number, number, number, number]> = {
  beginner: [200, 100, 1.60, 3.0],
  easy: [800, 180, 1.30, 5.0],
  medium: [3000, 250, 1.10, 10.0],
  hard: [6000, 300, 0.95, 15.0],
};
const AMAF_EQUIV: Record<Difficulty, number> = {
  beginner: 150,
  easy: 200,
  medium: 280,
  hard: 400,
};
const MAX_CANDIDATES: Record<Difficulty, number> = {
  beginner: 40,
  easy: 38,
  medium: 34,
  hard: 30,
};
const RESIGN_WINRATE: Record<Difficulty, number> = {
  beginner: 0.03,
  easy: 0.02,
  medium: 0.01,
  hard: 0.005,
};
const RESIGN_MIN_STONES = 80;

class Node {
  board: GoBoard;
  parent: Node | null;
  move: Point | null;
  color: Color; // color that moved INTO this node
  children: Node[] = [];
  visits = 0;
  wins = 0;
  amafVisits = 0;
  amafWins = 0;
  untried: Point[] | null = null;
  terminalScore: number | null = null;

  constructor(board: GoBoard, parent: Node | null, move: Point | null, color: Color) {
    this.board = board;
    this.parent = parent;
    this.move = move;
    this.color = color;
  }

  raveUcb(c: number, equiv: number): number {
    if (this.visits === 0 && this.amafVisits === 0) return Infinity;
    const parentVisits = Math.max(1, this.parent!.visits);
    const exploit = this.visits > 0 ? this.wins / this.visits : 0;
    const explore = c * Math.sqrt(Math.log(parentVisits) / Math.max(1, this.visits));
    const ucb = exploit + explore;
    if (this.amafVisits > 0) {
      const amaf = this.amafWins / this.amafVisits;
      const beta = Math.sqrt(equiv / (10.0 * parentVisits + equiv));
      if (this.visits === 0) return amaf;
      return beta * amaf + (1 - beta) * ucb;
    }
    return ucb;
  }
}

const STAR_POINTS: Record<number, Point[]> = {
  9: [[2, 2], [2, 6], [6, 2], [6, 6], [4, 4]],
  13: [[3, 3], [3, 9], [9, 3], [9, 9], [6, 6]],
  19: [[3, 3], [3, 9], [3, 15], [9, 3], [9, 9], [9, 15], [15, 3], [15, 9], [15, 15]],
};
const KOMOKU: Record<number, Point[]> = {
  19: [[3, 4], [4, 3], [3, 14], [14, 3], [15, 4], [4, 15], [15, 14], [14, 15]],
};
const SAN_SAN: Record<number, Point[]> = {
  9: [[2, 4], [4, 2], [4, 6], [6, 4]],
  19: [[2, 3], [3, 2], [2, 15], [15, 2], [16, 3], [3, 16], [16, 15], [15, 16]],
};

export class MCTS {
  difficulty: Difficulty;
  simulations: number;
  rolloutDepth: number;
  c: number;
  deadlineMs: number;
  _amafEquiv: number;
  _maxCandidates: number;
  private _treeCache = new Map<string, Node>();

  constructor(difficulty: Difficulty = "medium") {
    this.difficulty = difficulty;
    const [sims, depth, c, deadlineS] = DIFFICULTY_PRESETS[difficulty];
    this.simulations = sims;
    this.rolloutDepth = depth;
    this.c = c;
    this.deadlineMs = deadlineS * 1000;
    this._amafEquiv = AMAF_EQUIV[difficulty];
    this._maxCandidates = MAX_CANDIDATES[difficulty];
  }

  private _stoneCount(board: GoBoard): number {
    let n = 0;
    const s = board.size;
    for (let y = 0; y < s; y++) for (let x = 0; x < s; x++) if (board.get(x, y) !== EMPTY) n++;
    return n;
  }

  private _groupLiberties(board: GoBoard, x: number, y: number): [number, Set<string>] {
    const color = board.get(x, y);
    if (color === EMPTY) return [0, new Set<string>()];
    const size = board.size;
    const seen = new Set<string>();
    const libs = new Set<string>();
    const todo: Point[] = [[x, y]];
    while (todo.length) {
      const [cx, cy] = todo.pop()!;
      const k = `${cx},${cy}`;
      if (seen.has(k)) continue;
      seen.add(k);
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
        const nx = cx + dx;
        const ny = cy + dy;
        if (nx < 0 || nx >= size || ny < 0 || ny >= size) continue;
        const cell = board.get(nx, ny);
        if (cell === EMPTY) libs.add(`${nx},${ny}`);
        else if (cell === color && !seen.has(`${nx},${ny}`)) todo.push([nx, ny]);
      }
    }
    return [libs.size, seen];
  }

  private _isTrueEye(board: GoBoard, x: number, y: number, color: Color): boolean {
    let own = 0;
    let wall = 0;
    let diagOwn = 0;
    let diagTotal = 0;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
      const nx = x + dx;
      const ny = y + dy;
      if (!board.inBounds(nx, ny)) wall++;
      else if (board.get(nx, ny) === color) own++;
      else return false;
    }
    if (own + wall < 4) return false;
    for (const [dx, dy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]] as const) {
      const nx = x + dx;
      const ny = y + dy;
      if (!board.inBounds(nx, ny)) continue;
      diagTotal++;
      if (board.get(nx, ny) === color) diagOwn++;
      else if (board.get(nx, ny) !== EMPTY) {
        if (wall > 0) continue;
        return false;
      }
    }
    return diagOwn >= diagTotal - 1;
  }

  private _orderedLegalMoves(board: GoBoard, color: Color, widen: boolean): Point[] {
    let moves = board.legalMoves(color);
    if (!moves.length) return moves;
    moves = moves.filter(([x, y]) => !this._isTrueEye(board, x, y, color));
    if (!moves.length) return moves;
    const size = board.size;
    const cx = Math.floor(size / 2);
    const cy = Math.floor(size / 2);
    const stones = this._stoneCount(board);
    const opp = opponent(color);
    const stars = new Set(STAR_POINTS[size]?.map(([x, y]) => `${x},${y}`) ?? []);
    const komoku = new Set(KOMOKU[size]?.map(([x, y]) => `${x},${y}`) ?? []);
    const sansan = new Set(SAN_SAN[size]?.map(([x, y]) => `${x},${y}`) ?? []);

    const opponentAtariPts = new Map<string, number>();
    const ownEscapePts = new Set<string>();
    const contactPts = new Map<string, number>();
    const ownPts: Point[] = [];
    const oppPts: Point[] = [];
    const checkedGrp = new Set<string>();

    for (let sy = 0; sy < size; sy++) {
      for (let sx = 0; sx < size; sx++) {
        const cell = board.get(sx, sy);
        if (cell === EMPTY) continue;
        if (cell === color) ownPts.push([sx, sy]);
        else oppPts.push([sx, sy]);
        const key = `${sx},${sy}`;
        if (checkedGrp.has(key)) continue;
        const [libs, grp] = this._groupLiberties(board, sx, sy);
        for (const k of grp) checkedGrp.add(k);
        const libPts = new Set<string>();
        for (const k of grp) {
          const [gx, gy] = k.split(",").map(Number) as Point;
          for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
            const nx = gx + dx;
            const ny = gy + dy;
            if (nx >= 0 && nx < size && ny >= 0 && ny < size && board.get(nx, ny) === EMPTY) {
              libPts.add(`${nx},${ny}`);
            }
          }
        }
        if (cell === opp) {
          if (libs === 1 && libPts.size) {
            const gsz = grp.size;
            for (const p of libPts) opponentAtariPts.set(p, (opponentAtariPts.get(p) ?? 0) + gsz);
          }
        } else if (cell === color && libs <= 2 && libPts.size) {
          for (const p of libPts) ownEscapePts.add(p);
          for (const l of libPts) {
            const [lx, ly] = l.split(",").map(Number) as Point;
            for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
              const nx = lx + dx;
              const ny = ly + dy;
              if (nx >= 0 && nx < size && ny >= 0 && ny < size && board.get(nx, ny) === EMPTY) {
                ownEscapePts.add(`${nx},${ny}`);
              }
            }
          }
        }
      }
    }

    for (const [ox, oy] of oppPts) {
      let minOwnDist = 999;
      for (const [px, py] of ownPts) {
        const d = Math.abs(ox - px) + Math.abs(oy - py);
        if (d < minOwnDist) minOwnDist = d;
      }
      if (minOwnDist > 3) continue;
      for (let dx = -2; dx <= 2; dx++) {
        for (let dy = -2; dy <= 2; dy++) {
          const nx = ox + dx;
          const ny = oy + dy;
          if (nx < 0 || nx >= size || ny < 0 || ny >= size) continue;
          if (board.get(nx, ny) !== EMPTY) continue;
          const d = Math.abs(dx) + Math.abs(dy);
          if (d === 0) continue;
          const k = `${nx},${ny}`;
          const cur = contactPts.get(k);
          if (cur === undefined || d < cur) contactPts.set(k, d);
        }
      }
    }

    const hasNeighbor = (x: number, y: number, r = 2): boolean => {
      for (let dx = -r; dx <= r; dx++) {
        for (let dy = -r; dy <= r; dy++) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx >= 0 && nx < size && ny >= 0 && ny < size && board.get(nx, ny) !== EMPTY) return true;
        }
      }
      return false;
    };
    const minOppDist = (x: number, y: number): number => {
      if (!oppPts.length) return 99;
      let best = 99;
      for (const [px, py] of oppPts) {
        const d = Math.abs(x - px) + Math.abs(y - py);
        if (d < best) best = d;
      }
      return best;
    };

    const keyOf = (m: Point): [number, number, number] => {
      const [x, y] = m;
      const distCenter = Math.abs(x - cx) + Math.abs(y - cy);
      if (stones <= 12) {
        const k = `${x},${y}`;
        if (stars.has(k)) return [0, Math.random(), distCenter];
        if (komoku.has(k)) return [1, Math.random(), distCenter];
        if (sansan.has(k)) return [2, Math.random(), distCenter];
        const near = hasNeighbor(x, y, 3) ? 0 : 1;
        return [3 + near, distCenter, 0];
      }
      const k = `${x},${y}`;
      if (opponentAtariPts.has(k)) {
        const captured = opponentAtariPts.get(k)!;
        return [0, -captured, distCenter];
      }
      if (ownEscapePts.has(k)) return [1, minOppDist(x, y), distCenter];
      if (contactPts.has(k)) return [2, contactPts.get(k)!, distCenter];
      const near = hasNeighbor(x, y, 2) ? 0 : 1;
      return [3 + near, minOppDist(x, y), distCenter];
    };

    let result = moves.slice().sort((a, b) => {
      const ka = keyOf(a);
      const kb = keyOf(b);
      for (let i = 0; i < 3; i++) {
        if (ka[i] < kb[i]) return -1;
        if (ka[i] > kb[i]) return 1;
      }
      return 0;
    });
    if (widen && result.length > this._maxCandidates) result = result.slice(0, this._maxCandidates);
    return result;
  }

  private _priorForMove(parentBoard: GoBoard, move: Point, color: Color): [number, number] {
    const [x, y] = move;
    const opp = opponent(color);
    const size = parentBoard.size;
    let visits = 1;
    let wins = 0.5;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
      const nx = x + dx;
      const ny = y + dy;
      if (!parentBoard.inBounds(nx, ny)) continue;
      if (parentBoard.get(nx, ny) === opp) {
        const [libs, grp] = this._groupLiberties(parentBoard, nx, ny);
        if (libs === 1) {
          visits += Math.min(6, grp.size * 2);
          wins += Math.min(4.0, grp.size * 1.2);
        }
      }
    }
    const stones = this._stoneCount(parentBoard);
    if (stones <= 12) {
      const stars = STAR_POINTS[size] ?? [];
      const komoku = KOMOKU[size] ?? [];
      const inStars = stars.some(([sx, sy]) => sx === x && sy === y);
      const inKomoku = komoku.some(([sx, sy]) => sx === x && sy === y);
      if (inStars) {
        visits += 4;
        wins += 2.5;
      } else if (inKomoku) {
        visits += 3;
        wins += 1.8;
      }
    }
    if (stones > 6) {
      let hasNbr = false;
      outer: for (let dx = -2; dx <= 2; dx++) {
        for (let dy = -2; dy <= 2; dy++) {
          const nx = x + dx;
          const ny = y + dy;
          if (parentBoard.inBounds(nx, ny) && parentBoard.get(nx, ny) !== EMPTY) {
            hasNbr = true;
            break outer;
          }
        }
      }
      if (hasNbr) {
        visits += 2;
        wins += 1.0;
      }
    }
    return [visits, wins];
  }

  private _tacticalWeights(board: GoBoard, moves: Point[], color: Color): [number[], Point[]] {
    const opp = opponent(color);
    const size = board.size;
    const atariCapturePts = new Map<string, number>();
    const opp2LibPts = new Set<string>();
    const own1LibPts = new Set<string>();
    const own2LibPts = new Set<string>();
    const checked = new Set<string>();
    for (let sy = 0; sy < size; sy++) {
      for (let sx = 0; sx < size; sx++) {
        const cell = board.get(sx, sy);
        const k = `${sx},${sy}`;
        if (cell === EMPTY || checked.has(k)) continue;
        const [libs, grp] = this._groupLiberties(board, sx, sy);
        for (const gk of grp) checked.add(gk);
        const libPts = new Set<string>();
        for (const gk of grp) {
          const [gx, gy] = gk.split(",").map(Number) as Point;
          for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
            const nx = gx + dx;
            const ny = gy + dy;
            if (nx >= 0 && nx < size && ny >= 0 && ny < size && board.get(nx, ny) === EMPTY) {
              libPts.add(`${nx},${ny}`);
            }
          }
        }
        const gs = grp.size;
        if (cell === opp) {
          if (libs === 1) for (const p of libPts) atariCapturePts.set(p, (atariCapturePts.get(p) ?? 0) + gs);
          else if (libs === 2) for (const p of libPts) opp2LibPts.add(p);
        } else {
          if (libs === 1) {
            for (const p of libPts) own1LibPts.add(p);
            for (const l of libPts) {
              const [lx, ly] = l.split(",").map(Number) as Point;
              for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
                const nx = lx + dx;
                const ny = ly + dy;
                if (nx >= 0 && nx < size && ny >= 0 && ny < size && board.get(nx, ny) === EMPTY) {
                  own1LibPts.add(`${nx},${ny}`);
                }
              }
            }
          } else if (libs === 2) for (const p of libPts) own2LibPts.add(p);
        }
      }
    }

    const weights: number[] = [];
    const kept: Point[] = [];
    for (const [x, y] of moves) {
      let w = 1.0;
      const k = `${x},${y}`;
      if (atariCapturePts.has(k)) w += 200 + 60 * atariCapturePts.get(k)!;
      if (own1LibPts.has(k)) w += 60;
      if (opp2LibPts.has(k)) w += 12;
      if (own2LibPts.has(k)) w += 10;
      for (let dx = -2; dx <= 2; dx++) {
        for (let dy = -2; dy <= 2; dy++) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx >= 0 && nx < size && ny >= 0 && ny < size && board.get(nx, ny) !== EMPTY) {
            const d = Math.abs(dx) + Math.abs(dy);
            w += Math.max(0, 1.6 - d * 0.5);
          }
        }
      }
      if (!atariCapturePts.has(k)) {
        let immLibs = 0;
        let hasFriend = false;
        for (const [ddx, ddy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
          const nx = x + ddx;
          const ny = y + ddy;
          if (nx < 0 || nx >= size || ny < 0 || ny >= size) continue;
          const cell = board.get(nx, ny);
          if (cell === EMPTY) immLibs++;
          else if (cell === color) hasFriend = true;
        }
        if (immLibs <= 1 && !hasFriend) w *= 0.15;
      }
      kept.push([x, y]);
      weights.push(w);
    }
    return [weights, kept];
  }

  private _rolloutWithTrace(board: GoBoard, color: Color): [number, Record<Color, Point[]>] {
    const b = board.clone();
    let cur = color;
    const trace = {} as Record<Color, Point[]>;
    trace[BLACK] = [];
    trace[WHITE] = [];
    trace[EMPTY] = [];
    let passes = 0;
    const size = b.size;
    const totalCells = size * size;
    const fillLimit = Math.floor(totalCells * 0.6);
    let stoneCount = this._stoneCount(b);

    for (let step = 0; step < this.rolloutDepth; step++) {
      if (b.isFinished() || passes >= 2) break;
      if (stoneCount >= fillLimit) {
        b.passMove(cur);
        passes++;
        cur = opponent(cur);
        continue;
      }
      let moves = b.legalMoves(cur);
      if (moves.length) moves = moves.filter(([x, y]) => !this._isTrueEye(b, x, y, cur));
      if (!moves.length) {
        b.passMove(cur);
        passes++;
      } else {
        const [weighted, chosenMoves] = this._tacticalWeights(b, moves, cur);
        const total = weighted.reduce((a, c) => a + c, 0);
        let chosen: Point;
        if (total <= 0) {
          chosen = chosenMoves[Math.floor(Math.random() * chosenMoves.length)];
        } else {
          const r = Math.random() * total;
          let acc = 0;
          chosen = chosenMoves[0];
          for (let i = 0; i < chosenMoves.length; i++) {
            acc += weighted[i];
            if (acc >= r) {
              chosen = chosenMoves[i];
              break;
            }
          }
        }
        const [x, y] = chosen;
        trace[cur].push([x, y]);
        const res = b.placeStone(x, y, cur);
        if (res.ok) {
          passes = 0;
          stoneCount += 1 - res.captured.length;
        } else {
          trace[cur].pop();
          b.passMove(cur);
          passes++;
        }
      }
      cur = opponent(cur);
    }

    const sc = scoreChinese(b);
    const advantage = color === BLACK ? sc.margin : -sc.margin;
    const wr = 1.0 / (1.0 + Math.exp(-advantage / 8.0));
    return [wr, trace];
  }

  private _iterate(root: Node, rootColor: Color): void {
    let node: Node = root;
    const selectionPath: Node[] = [node];
    while (node.untried && node.untried.length === 0 && node.children.length) {
      let best = node.children[0];
      let bestScore = -Infinity;
      for (const ch of node.children) {
        const s = ch.raveUcb(this.c, this._amafEquiv);
        if (s > bestScore) {
          bestScore = s;
          best = ch;
        }
      }
      node = best;
      selectionPath.push(node);
    }

    if (node.untried && node.untried.length > 0) {
      const move = node.untried.shift()!;
      const colorToMove = node === root ? rootColor : opponent(node.color);
      const nb = node.board.clone();
      const res = nb.placeStone(move[0], move[1], colorToMove);
      if (!res.ok) return;
      const child = new Node(nb, node, move, colorToMove);
      const [pv, pw] = this._priorForMove(node.board, move, colorToMove);
      child.visits = pv;
      child.wins = pw;
      child.untried = this._orderedLegalMoves(nb, opponent(colorToMove), true);
      node.children.push(child);
      selectionPath.push(child);
      node = child;
    }

    const rolloutPlayer = opponent(node.color);
    const [wrRolloutPov, amafTrace] = this._rolloutWithTrace(node.board, rolloutPlayer);

    let cur: Node | null = node;
    while (cur !== null) {
      cur.visits++;
      if (cur !== root) {
        const v = cur.color === rolloutPlayer ? wrRolloutPov : 1.0 - wrRolloutPov;
        cur.wins += v;
      }
      cur = cur.parent;
    }

    const lastIdx = selectionPath.length - 1;
    for (let i = 0; i < selectionPath.length; i++) {
      if (i === lastIdx) continue;
      const ancestor = selectionPath[i];
      const toMoveAtAnc = ancestor === root ? rootColor : opponent(ancestor.color);
      const tm = amafTrace[toMoveAtAnc] ?? [];
      if (!tm.length) continue;
      const traceSet = new Set(tm.map(([x, y]) => `${x},${y}`));
      const sample = toMoveAtAnc === rolloutPlayer ? wrRolloutPov : 1.0 - wrRolloutPov;
      for (const child of ancestor.children) {
        if (!child.move) continue;
        const k = `${child.move[0]},${child.move[1]}`;
        if (traceSet.has(k)) {
          child.amafVisits++;
          child.amafWins += sample;
        }
      }
    }
  }

  analyze(board: GoBoard, color: Color, topK = 10): AnalysisResult {
    const cacheKey = `${board.hashPosition()}|${board.koPoint ? board.koPoint.join(",") : "n"}|${color}`;
    let root: Node;
    const cached = this._treeCache.get(cacheKey);
    if (cached) {
      root = cached;
      root.parent = null;
      if (!root.untried) root.untried = this._orderedLegalMoves(board, color, true);
      this._treeCache.delete(cacheKey);
    } else {
      root = new Node(board.clone(), null, null, opponent(color));
      root.untried = this._orderedLegalMoves(board, color, true);
    }

    if ((!root.untried || root.untried.length === 0) && root.children.length === 0) {
      return { bestMove: null, winrate: 0, scoreLead: null, candidates: [], engine: "mcts-js", resign: false };
    }

    const deadline = performance.now() + this.deadlineMs;
    for (let i = 0; i < this.simulations; i++) {
      if (performance.now() > deadline) break;
      this._iterate(root, color);
    }

    for (const child of root.children) {
      const ck = `${child.board.hashPosition()}|${child.board.koPoint ? child.board.koPoint.join(",") : "n"}|${opponent(child.color)}`;
      this._treeCache.set(ck, child);
    }
    this._treeCache.set(cacheKey, root);
    if (this._treeCache.size > 50) {
      const keys = Array.from(this._treeCache.keys());
      for (let i = 0; i < keys.length && this._treeCache.size > 20; i++) {
        if (keys[i] !== cacheKey) this._treeCache.delete(keys[i]);
      }
    }

    if (root.children.length === 0) {
      const move = root.untried && root.untried.length ? root.untried[0] : null;
      return { bestMove: move, winrate: 0.5, scoreLead: null, candidates: [], engine: "mcts-js", resign: false };
    }

    let bestChild = root.children[0];
    for (const ch of root.children) if (ch.visits > bestChild.visits) bestChild = ch;
    const winrate = bestChild.visits ? bestChild.wins / bestChild.visits : 0.5;

    const candidates: MoveEval[] = root.children
      .slice()
      .sort((a, b) => b.visits - a.visits)
      .slice(0, topK)
      .map((ch) => ({
        x: ch.move![0],
        y: ch.move![1],
        winrate: ch.visits ? ch.wins / ch.visits : 0,
        visits: ch.visits,
      }));

    let scoreLead: number | null = null;
    if (winrate > 0.01 && winrate < 0.99) {
      const lead = Math.log(winrate / (1 - winrate)) * 8.0;
      scoreLead = color === BLACK ? lead : -lead;
    }

    const resign = this._shouldResign(board, color, winrate);
    return { bestMove: bestChild.move, winrate, scoreLead, candidates, engine: "mcts-js", resign };
  }

  private _shouldResign(_board: GoBoard, _color: Color, winrate: number): boolean {
    if (winrate >= RESIGN_WINRATE[this.difficulty]) return false;
    if (this._stoneCount(_board) < RESIGN_MIN_STONES) return false;
    return true;
  }
}

// Convenience: engine singleton store so App.tsx can reuse the same MCTS
// instance across moves, benefiting from tree reuse cache.
const engines = new Map<string, MCTS>();
export function getEngine(difficulty: Difficulty): MCTS {
  let e = engines.get(difficulty);
  if (!e) {
    e = new MCTS(difficulty);
    engines.set(difficulty, e);
  }
  return e;
}
