// Lightweight client-side Go rules mirror for instant click feedback and
// offline play. The server remains authoritative; this is used to render
// the board immediately and validate before round-trip.

export const EMPTY = 0;
export const BLACK = 1;
export const WHITE = 2;

export type Cell = 0 | 1 | 2;

export interface PlaceResult {
  ok: boolean;
  captured: { x: number; y: number }[];
  reason: string | null;
}

export class GoBoard {
  size: number;
  grid: Cell[][];
  captures: { black: number; white: number };
  moveLog: { x: number; y: number; color: Cell }[];
  koPoint: { x: number; y: number } | null;

  constructor(size = 19) {
    this.size = size;
    this.grid = Array.from({ length: size }, () => Array<Cell>(size).fill(0));
    this.captures = { black: 0, white: 0 };
    this.moveLog = [];
    this.koPoint = null;
  }

  static fromGrid(size: number, grid: number[][], captures = { black: 0, white: 0 }): GoBoard {
    const b = new GoBoard(size);
    b.grid = grid.map((row) => row.map((c) => c as Cell));
    b.captures = { ...captures };
    return b;
  }

  private inBounds(x: number, y: number): boolean {
    return x >= 0 && x < this.size && y >= 0 && y < this.size;
  }

  private neighbors(x: number, y: number): [number, number][] {
    const out: [number, number][] = [];
    if (x > 0) out.push([x - 1, y]);
    if (x < this.size - 1) out.push([x + 1, y]);
    if (y > 0) out.push([x, y - 1]);
    if (y < this.size - 1) out.push([x, y + 1]);
    return out;
  }

  private getGroup(x: number, y: number): Set<string> {
    const color = this.grid[y][x];
    if (color === EMPTY) return new Set();
    const seen = new Set<string>();
    const stack = [[x, y]];
    while (stack.length) {
      const [cx, cy] = stack.pop()!;
      const key = `${cx},${cy}`;
      if (seen.has(key)) continue;
      seen.add(key);
      for (const [nx, ny] of this.neighbors(cx, cy)) {
        if (this.grid[ny][nx] === color && !seen.has(`${nx},${ny}`)) {
          stack.push([nx, ny]);
        }
      }
    }
    return seen;
  }

  private groupLiberties(group: Set<string>): Set<string> {
    const libs = new Set<string>();
    for (const key of group) {
      const [x, y] = key.split(",").map(Number);
      for (const [nx, ny] of this.neighbors(x, y)) {
        if (this.grid[ny][nx] === EMPTY) libs.add(`${nx},${ny}`);
      }
    }
    return libs;
  }

  isLegal(x: number, y: number, color: Cell): boolean {
    if (!this.inBounds(x, y) || this.grid[y][x] !== EMPTY) return false;
    if (this.koPoint && this.koPoint.x === x && this.koPoint.y === y) return false;
    // simulate
    const snap = this.snapshot();
    this.grid[y][x] = color;
    const opp = color === BLACK ? WHITE : BLACK;
    const captured: [number, number][] = [];
    for (const [nx, ny] of this.neighbors(x, y)) {
      if (this.grid[ny][nx] === opp) {
        const grp = this.getGroup(nx, ny);
        if (this.groupLiberties(grp).size === 0) {
          for (const k of grp) {
            const [gx, gy] = k.split(",").map(Number);
            captured.push([gx, gy]);
          }
        }
      }
    }
    for (const [cx, cy] of captured) this.grid[cy][cx] = EMPTY;
    const own = this.getGroup(x, y);
    const legal = this.groupLiberties(own).size > 0;
    this.restore(snap);
    return legal;
  }

  place(x: number, y: number, color: Cell): PlaceResult {
    if (!this.inBounds(x, y) || this.grid[y][x] !== EMPTY) {
      return { ok: false, captured: [], reason: "occupied" };
    }
    if (this.koPoint && this.koPoint.x === x && this.koPoint.y === y) {
      return { ok: false, captured: [], reason: "ko" };
    }
    if (!this.isLegal(x, y, color)) {
      return { ok: false, captured: [], reason: "illegal" };
    }
    this.grid[y][x] = color;
    const opp = color === BLACK ? WHITE : BLACK;
    const captured: { x: number; y: number }[] = [];
    for (const [nx, ny] of this.neighbors(x, y)) {
      if (this.grid[ny][nx] === opp) {
        const grp = this.getGroup(nx, ny);
        if (this.groupLiberties(grp).size === 0) {
          for (const k of grp) {
            const [gx, gy] = k.split(",").map(Number);
            captured.push({ x: gx, y: gy });
          }
        }
      }
    }
    for (const c of captured) this.grid[c.y][c.x] = EMPTY;
    if (color === BLACK) this.captures.black += captured.length;
    else this.captures.white += captured.length;

    // ko detection
    this.koPoint = null;
    if (captured.length === 1) {
      const own = this.getGroup(x, y);
      if (own.size === 1 && this.groupLiberties(own).size === 1) {
        this.koPoint = captured[0];
      }
    }
    this.moveLog.push({ x, y, color });
    return { ok: true, captured, reason: null };
  }

  pass(color: Cell): void {
    this.koPoint = null;
    // Sentinel pass entry: x=-1 marks a pass; color preserved for turn logic.
    this.moveLog.push({ x: -1, y: -1, color });
  }

  toMove(): Cell {
    if (this.moveLog.length === 0) return BLACK;
    const last = this.moveLog[this.moveLog.length - 1];
    return last.color === BLACK ? WHITE : BLACK;
  }

  isFinished(): boolean {
    return (
      this.moveLog.length >= 2 &&
      this.moveLog[this.moveLog.length - 1].x === -1 &&
      this.moveLog[this.moveLog.length - 2].x === -1
    );
  }

  private snapshot() {
    return {
      grid: this.grid.map((r) => [...r]),
      captures: { ...this.captures },
      koPoint: this.koPoint ? { ...this.koPoint } : null,
      logLen: this.moveLog.length,
    };
  }

  private restore(s: ReturnType<GoBoard["snapshot"]>) {
    this.grid = s.grid;
    this.captures = s.captures;
    this.koPoint = s.koPoint;
    this.moveLog.length = s.logLen;
  }
}
