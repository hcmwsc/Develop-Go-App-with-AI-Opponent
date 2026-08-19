import { useEffect, useRef, useCallback } from "react";
import type { CandidateMove, MoveInfo } from "../types";

interface BoardProps {
  size: number;
  grid: number[][];
  lastMove?: MoveInfo | null;
  candidates?: CandidateMove[];
  showCandidates: boolean;
  showWinrateHeatmap: boolean;
  thinking: boolean;
  onPlay: (x: number, y: number) => void;
  hoverColor: number; // 1 black, 2 white
  disabled?: boolean;
}

const STAR_POINTS: Record<number, [number, number][]> = {
  9: [[2, 2], [2, 6], [6, 2], [6, 6], [4, 4]],
  13: [[3, 3], [3, 9], [9, 3], [9, 9], [6, 6]],
  19: [
    [3, 3], [3, 9], [3, 15],
    [9, 3], [9, 9], [9, 15],
    [15, 3], [15, 9], [15, 15],
  ],
};

/**
 * Shared board layout. The board is drawn inside the canvas with a one-cell
 * margin on every side, so the total span is cell*(size+1). When the canvas
 * is not perfectly square, we use min(W,H) for the cell and center the board
 * so drawing and hit-testing stay consistent.
 *
 * Convention: intersection (x, y) is at pixel
 *   (offsetX + cell*(x+1), offsetY + cell*(y+1))
 */
function computeLayout(cssW: number, cssH: number, size: number) {
  const cell = Math.min(cssW, cssH) / (size + 1);
  const boardSpan = cell * (size + 1);
  const offsetX = (cssW - boardSpan) / 2;
  const offsetY = (cssH - boardSpan) / 2;
  return { cell, offsetX, offsetY };
}

/** Convert a pixel position inside the canvas to a board intersection. */
function pixelToBoard(
  pxX: number,
  pxY: number,
  cssW: number,
  cssH: number,
  size: number
): { x: number; y: number } {
  const { cell, offsetX, offsetY } = computeLayout(cssW, cssH, size);
  const x = Math.round((pxX - offsetX) / cell - 1);
  const y = Math.round((pxY - offsetY) / cell - 1);
  return { x, y };
}

export function Board({
  size,
  grid,
  lastMove,
  candidates = [],
  showCandidates,
  showWinrateHeatmap,
  thinking,
  onPlay,
  hoverColor,
  disabled,
}: BoardProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hoverRef = useRef<{ x: number; y: number } | null>(null);
  const rafRef = useRef<number | null>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth;
    const cssH = canvas.clientHeight;
    if (cssW === 0 || cssH === 0) return;

    // Resize the backing store to match the displayed size (per axis).
    const pxW = Math.floor(cssW * dpr);
    const pxH = Math.floor(cssH * dpr);
    if (canvas.width !== pxW) canvas.width = pxW;
    if (canvas.height !== pxH) canvas.height = pxH;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const { cell, offsetX, offsetY } = computeLayout(cssW, cssH, size);
    // Helper: intersection (x, y) -> pixel center
    const px = (x: number) => offsetX + cell * (x + 1);
    const py = (y: number) => offsetY + cell * (y + 1);

    // Board background (wood). Fill the whole canvas so non-square areas
    // don't show transparent gaps.
    ctx.fillStyle = "#dcb35c";
    ctx.fillRect(0, 0, cssW, cssH);

    // Grid lines: from (1..size) in board coords, i.e. px(i) for i in 0..size-1
    ctx.strokeStyle = "#3a2a10";
    ctx.lineWidth = Math.max(0.5, cell * 0.02);
    ctx.beginPath();
    for (let i = 0; i < size; i++) {
      const p = cell * (i + 1);
      // vertical line at x = i
      ctx.moveTo(offsetX + p, offsetY + cell);
      ctx.lineTo(offsetX + p, offsetY + cell * size);
      // horizontal line at y = i
      ctx.moveTo(offsetX + cell, offsetY + p);
      ctx.lineTo(offsetX + cell * size, offsetY + p);
    }
    ctx.stroke();

    // Star points
    ctx.fillStyle = "#3a2a10";
    const stars = STAR_POINTS[size] || [];
    for (const [sx, sy] of stars) {
      ctx.beginPath();
      ctx.arc(px(sx), py(sy), Math.max(2, cell * 0.08), 0, Math.PI * 2);
      ctx.fill();
    }

    // Winrate heatmap (subtle background tint)
    if (showWinrateHeatmap && candidates.length > 0) {
      for (const c of candidates) {
        const alpha = Math.max(0, Math.min(0.55, (c.winrate - 0.5) * 0.9));
        if (alpha <= 0.02) continue;
        ctx.fillStyle = `rgba(74, 158, 255, ${alpha})`;
        ctx.beginPath();
        ctx.arc(px(c.x), py(c.y), cell * 0.42, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Stones
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const v = grid[y]?.[x];
        if (v === 1 || v === 2) {
          drawStone(ctx, px(x), py(y), cell * 0.46, v);
        }
      }
    }

    // Last move marker
    if (lastMove) {
      const cx = px(lastMove.x);
      const cy = py(lastMove.y);
      ctx.strokeStyle = lastMove.color === "black" ? "#fff" : "#000";
      ctx.lineWidth = Math.max(1, cell * 0.04);
      ctx.beginPath();
      ctx.arc(cx, cy, cell * 0.18, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Candidate move markers (small dots with rank)
    if (showCandidates) {
      const sorted = [...candidates].sort((a, b) => b.winrate - a.winrate);
      sorted.forEach((c, idx) => {
        const cx = px(c.x);
        const cy = py(c.y);
        const r = cell * (idx === 0 ? 0.22 : 0.14);
        ctx.fillStyle = idx === 0 ? "rgba(76, 175, 80, 0.85)" : "rgba(74, 158, 255, 0.65)";
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fill();
        if (idx === 0) {
          ctx.fillStyle = "#fff";
          ctx.font = `${Math.floor(cell * 0.2)}px sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(`${Math.round(c.winrate * 100)}`, cx, cy);
        }
      });
    }

    // Hover preview
    if (!disabled && hoverRef.current) {
      const { x, y } = hoverRef.current;
      if (x >= 0 && x < size && y >= 0 && y < size && grid[y]?.[x] === 0) {
        ctx.globalAlpha = 0.45;
        drawStone(ctx, px(x), py(y), cell * 0.46, hoverColor);
        ctx.globalAlpha = 1;
      }
    }
  }, [size, grid, lastMove, candidates, showCandidates, showWinrateHeatmap, hoverColor, disabled]);

  // Schedule draw on prop/state change
  useEffect(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(draw);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [draw]);

  // Resize observer
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(draw);
    });
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [draw]);

  const toBoardCoord = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return pixelToBoard(
      clientX - rect.left,
      clientY - rect.top,
      rect.width,
      rect.height,
      size
    );
  };

  const handleMove = (e: React.MouseEvent | React.TouchEvent) => {
    const canvas = canvasRef.current;
    if (!canvas || disabled) return;
    let clientX: number, clientY: number;
    if ("touches" in e) {
      const t = e.touches[0];
      clientX = t.clientX;
      clientY = t.clientY;
    } else {
      clientX = e.clientX;
      clientY = e.clientY;
    }
    const { x, y } = toBoardCoord(clientX, clientY);
    if (hoverRef.current?.x !== x || hoverRef.current?.y !== y) {
      hoverRef.current = { x, y };
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(draw);
    }
  };

  const handleClick = (e: React.MouseEvent) => {
    if (disabled) return;
    const { x, y } = toBoardCoord(e.clientX, e.clientY);
    if (x >= 0 && x < size && y >= 0 && y < size) {
      onPlay(x, y);
    }
    hoverRef.current = null;
  };

  const handleLeave = () => {
    hoverRef.current = null;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(draw);
  };

  return (
    <canvas
      ref={canvasRef}
      style={{ width: "100%", height: "100%", cursor: disabled ? "default" : "pointer" }}
      onMouseMove={handleMove}
      onMouseDown={handleClick}
      onMouseLeave={handleLeave}
      onTouchStart={handleMove}
      onTouchEnd={(e) => {
        if (disabled) return;
        const t = e.changedTouches[0];
        const { x, y } = toBoardCoord(t.clientX, t.clientY);
        if (x >= 0 && x < size && y >= 0 && y < size) onPlay(x, y);
      }}
      aria-label={`Go board ${size}x${size}${thinking ? ", AI thinking" : ""}`}
    />
  );
}

function drawStone(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  color: number
) {
  // shadow
  ctx.fillStyle = "rgba(0,0,0,0.25)";
  ctx.beginPath();
  ctx.arc(cx + r * 0.08, cy + r * 0.12, r, 0, Math.PI * 2);
  ctx.fill();
  // stone
  const grad = ctx.createRadialGradient(
    cx - r * 0.3,
    cy - r * 0.3,
    r * 0.1,
    cx,
    cy,
    r
  );
  if (color === 1) {
    grad.addColorStop(0, "#444");
    grad.addColorStop(1, "#000");
  } else {
    grad.addColorStop(0, "#fff");
    grad.addColorStop(1, "#c8c8c8");
  }
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
}
