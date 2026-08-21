import { useEffect, useRef, useMemo } from "react";
import type { ReviewData, ReviewEntry, Player } from "../types";

interface ReviewPanelProps {
  data: ReviewData;
  step: number; // 0 = 初始局面, 1..N = 走完第 step 步后
  humanColor: Player; // 玩家执色，用于把走子方视角胜率统一为「玩家视角」展示
  onStepChange: (step: number) => void;
}

/** 把 ReviewEntry 的胜率（从当前回合方视角）转换到黑方视角，便于画曲线。 */
function blackView(wr: number | null, color: string): number | null {
  if (wr === null) return null;
  return color === "black" ? wr : 1 - wr;
}

/** 把走子方视角胜率换算为玩家（humanColor）视角，用于侧栏数值展示。 */
function toHumanView(wr: number | null, moveColor: Player, humanColor: Player): number | null {
  if (wr === null) return null;
  return moveColor === humanColor ? wr : 1 - wr;
}

export function ReviewPanel({ data, step, humanColor, onStepChange }: ReviewPanelProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const total = data.entries.length;

  // 胜率曲线数据（黑方视角）
  const curve = useMemo(() => {
    const pts: { step: number; wr: number | null }[] = [];
    pts.push({ step: 0, wr: 0.5 }); // 初始均势
    data.entries.forEach((e, i) => {
      const bw = blackView(e.post_winrate, e.color);
      pts.push({ step: i + 1, wr: bw });
    });
    return pts;
  }, [data]);

  // 画胜率曲线
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const padL = 28, padR = 8, padT = 8, padB = 16;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;

    // 50% 中线
    ctx.strokeStyle = "#888";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(padL, padT + plotH / 2);
    ctx.lineTo(padL + plotW, padT + plotH / 2);
    ctx.stroke();
    ctx.setLineDash([]);

    // 胜率区域填充（黑>50% 灰色，白>50% 浅色）
    ctx.fillStyle = "rgba(40,40,40,0.08)";
    ctx.fillRect(padL, padT, plotW, plotH / 2);

    if (curve.length < 2) return;
    const xAt = (s: number) => padL + (total > 0 ? (s / total) * plotW : 0);
    const yAt = (wr: number) => padT + (1 - wr) * plotH;

    // 黑方胜率折线
    ctx.strokeStyle = "#222";
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    let started = false;
    curve.forEach((p) => {
      if (p.wr === null) return;
      const x = xAt(p.step);
      const y = yAt(p.wr);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();

    // 关键转折点标记
    data.entries.forEach((e, i) => {
      if (!e.is_key_move) return;
      const bw = blackView(e.post_winrate, e.color);
      if (bw === null) return;
      const x = xAt(i + 1);
      const y = yAt(bw);
      ctx.fillStyle = "#d33";
      ctx.beginPath();
      ctx.arc(x, y, 3.5, 0, Math.PI * 2);
      ctx.fill();
    });

    // 当前步指示线
    if (total > 0) {
      const x = xAt(step);
      ctx.strokeStyle = "#1a7f37";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + plotH);
      ctx.stroke();
    }

    // 刻度
    ctx.fillStyle = "#666";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "right";
    ctx.fillText("100%", padL - 4, padT + 8);
    ctx.fillText("50%", padL - 4, padT + plotH / 2 + 3);
    ctx.fillText("0%", padL - 4, padT + plotH - 1);
  }, [curve, data, step, total]);

  const current: ReviewEntry | null = step > 0 ? data.entries[step - 1] : null;

  return (
    <div className="panel review-panel">
      <h3>复盘</h3>
      <div className="review-controls">
        <button onClick={() => onStepChange(0)} disabled={step === 0}>|&lt;</button>
        <button onClick={() => onStepChange(Math.max(0, step - 1))} disabled={step === 0}>&lt;</button>
        <span className="step-label">
          {step} / {total}
        </span>
        <button onClick={() => onStepChange(Math.min(total, step + 1))} disabled={step >= total}>&gt;</button>
        <button onClick={() => onStepChange(total)} disabled={step >= total}>&gt;|</button>
      </div>
      <input
        type="range"
        min={0}
        max={total}
        value={step}
        onChange={(e) => onStepChange(Number(e.target.value))}
        className="review-slider"
      />
      <div className="review-curve">
        <canvas ref={canvasRef} />
      </div>
      <div className="review-current">
        {current ? (
          <>
            <div className="info-row">
              <span className="label">第 {current.move_number} 手</span>
              <span className={current.color}>
                {current.color === "black" ? "黑" : "白"}
                {current.move ? ` (${current.move[0]},${current.move[1]})` : " 弃权"}
              </span>
            </div>
            <div className="info-row">
              <span className="label">走子前胜率（玩家视角）</span>
              <span>
                {current.pre_winrate !== null
                  ? (toHumanView(current.pre_winrate, current.color, humanColor)! * 100).toFixed(1) + "%"
                  : "—"}
              </span>
            </div>
            <div className="info-row">
              <span className="label">走子后胜率（玩家视角）</span>
              <span>
                {current.post_winrate !== null
                  ? (toHumanView(current.post_winrate, current.color, humanColor)! * 100).toFixed(1) + "%"
                  : "—"}
              </span>
            </div>
            {current.post_score_lead !== null && (
              <div className="info-row">
                <span className="label">目差</span>
                <span>{current.post_score_lead.toFixed(1)}</span>
              </div>
            )}
            {current.best_move && (
              <div className="info-row">
                <span className="label">AI 推荐</span>
                <span className="recommend">
                  ({current.best_move[0]},{current.best_move[1]})
                </span>
              </div>
            )}
            {current.is_key_move && (
              <div className="key-move-flag">关键转折点</div>
            )}
          </>
        ) : (
          <div className="info-row">
            <span className="label">初始局面</span>
            <span>胜率 50.0%</span>
          </div>
        )}
      </div>
    </div>
  );
}
