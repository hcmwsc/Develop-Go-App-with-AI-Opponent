import type { GameState, CandidateMove, EngineStatus, Player, Difficulty } from "../types";
import { setApiUrl } from "../config";

interface ControlPanelProps {
  game: GameState | null;
  engineInfo: EngineStatus | null;
  config: { boardSize: number; komi: number; playerColor: Player; difficulty: Difficulty };
  onConfigChange: (c: ControlPanelProps["config"]) => void;
  onStart: () => void;
  onPass: () => void;
  onUndo: () => void;
  onResign: () => void;
  candidates: CandidateMove[];
  showCandidates: boolean;
  showHeatmap: boolean;
  onToggleCandidates: () => void;
  onToggleHeatmap: () => void;
  disabled: boolean;
  winrate: number;
}

const BOARD_SIZES = [9, 13, 19];

const DIFFICULTY_OPTIONS: { value: Difficulty; label: string; desc: string }[] = [
  { value: "beginner", label: "入门", desc: "几乎随机走子，适合初学者" },
  { value: "easy", label: "初级", desc: "浅搜索，会犯明显错误" },
  { value: "medium", label: "中级", desc: "默认强度，正常对局" },
  { value: "hard", label: "高级", desc: "深搜索，走子更稳健" },
];

export function ControlPanel({
  game,
  engineInfo,
  config,
  onConfigChange,
  onStart,
  onPass,
  onUndo,
  onResign,
  candidates,
  showCandidates,
  showHeatmap,
  onToggleCandidates,
  onToggleHeatmap,
  disabled,
  winrate,
}: ControlPanelProps) {
  const sorted = [...candidates].sort((a, b) => b.winrate - a.winrate).slice(0, 10);
  return (
    <div className="sidebar">
      <div className="panel">
        <h3>对局设置</h3>
        <div className="field">
          <label>棋盘大小</label>
          <select
            value={config.boardSize}
            onChange={(e) =>
              onConfigChange({ ...config, boardSize: Number(e.target.value) })
            }
            disabled={!!game && !game.finished}
          >
            {BOARD_SIZES.map((s) => (
              <option key={s} value={s}>
                {s} × {s}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>执子颜色</label>
          <select
            value={config.playerColor}
            onChange={(e) =>
              onConfigChange({
                ...config,
                playerColor: e.target.value as Player,
              })
            }
            disabled={!!game && !game.finished}
          >
            <option value="black">黑 (先手)</option>
            <option value="white">白 (后手)</option>
          </select>
        </div>
        <div className="field">
          <label>AI 难度</label>
          <select
            value={config.difficulty}
            onChange={(e) =>
              onConfigChange({
                ...config,
                difficulty: e.target.value as Difficulty,
              })
            }
            disabled={!!game && !game.finished}
          >
            {DIFFICULTY_OPTIONS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label} — {d.desc}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>贴目</label>
          <input
            type="number"
            step="0.5"
            value={config.komi}
            onChange={(e) =>
              onConfigChange({ ...config, komi: Number(e.target.value) })
            }
            disabled={!!game && !game.finished}
          />
        </div>
        <div className="btn-row">
          <button className="primary" onClick={onStart}>
            {game && !game.finished ? "重新开始" : "开始对局"}
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>对局操作</h3>
        <div className="btn-row">
          <button onClick={onPass} disabled={disabled}>
            弃权 (Pass)
          </button>
          <button onClick={onUndo} disabled={disabled}>
            悔棋
          </button>
          <button onClick={onResign} disabled={disabled}>
            认输
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>显示</h3>
        <div className="btn-row">
          <button
            onClick={onToggleCandidates}
            style={{
              background: showCandidates ? "var(--accent-dim)" : undefined,
              borderColor: showCandidates ? "var(--accent)" : undefined,
            }}
          >
            候选点 {showCandidates ? "✓" : ""}
          </button>
          <button
            onClick={onToggleHeatmap}
            style={{
              background: showHeatmap ? "var(--accent-dim)" : undefined,
              borderColor: showHeatmap ? "var(--accent)" : undefined,
            }}
          >
            胜率热力图 {showHeatmap ? "✓" : ""}
          </button>
        </div>
      </div>

      {sorted.length > 0 && (
        <div className="panel">
          <h3>候选走子 (Top 10)</h3>
          <div className="candidate-list">
            {sorted.map((c, i) => (
              <div key={`${c.x}-${c.y}`} className="candidate-item">
                <span className="candidate-rank">{i + 1}</span>
                <div className="candidate-bar">
                  <div
                    className="fill"
                    style={{ width: `${Math.round(c.winrate * 100)}%` }}
                  />
                </div>
                <span className="candidate-winrate">
                  {(c.winrate * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {game?.finished && game.score && (
        <div className="panel">
          <h3>终局结算</h3>
          <div className="info-row">
            <span className="label">黑</span>
            <span>{game.score.black.toFixed(1)}</span>
          </div>
          <div className="info-row">
            <span className="label">白 (含贴目 {game.score.komi})</span>
            <span>{game.score.white.toFixed(1)}</span>
          </div>
          <div className="info-row">
            <span className="label">结果</span>
            <span>
              {game.score.winner === "draw"
                ? "平局"
                : `${game.score.winner === "black" ? "黑" : "白"}胜 ${Math.abs(game.score.margin).toFixed(1)} 目`}
            </span>
          </div>
        </div>
      )}

      <div className="panel">
        <h3>引擎状态</h3>
        <div className="info-row">
          <span className="label">当前引擎</span>
          <span>{game?.engine ?? engineInfo?.engine ?? "—"}</span>
        </div>
        <div className="info-row">
          <span className="label">本局难度</span>
          <span>{game?.difficulty ?? "—"}</span>
        </div>
        <div className="info-row">
          <span className="label">KataGo 可用</span>
          <span>{engineInfo?.katago_available ? "是" : "否 (用 MCTS)"}</span>
        </div>
        <div className="info-row">
          <span className="label">MCTS 模拟次数</span>
          <span>{engineInfo?.mcts_simulations ?? "—"}</span>
        </div>
        <div className="info-row">
          <span className="label">当前胜率</span>
          <span>{(winrate * 100).toFixed(1)}%</span>
        </div>
      </div>

      <div className="panel">
        <h3>服务器设置</h3>
        <div className="field">
          <label>后端地址</label>
          <input
            type="text"
            placeholder="如 http://192.168.1.100:8000"
            defaultValue={typeof localStorage !== "undefined" ? localStorage.getItem("weiqi_api_url") || "" : ""}
            onChange={(e) => setApiUrl(e.target.value.trim())}
          />
        </div>
        <div className="info-row">
          <span className="label" style={{ fontSize: "0.8em", color: "var(--text-dim)" }}>
            留空 = 同源（桌面端内嵌后端）。手机端填写电脑 IP:端口。
          </span>
        </div>
      </div>
    </div>
  );
}
