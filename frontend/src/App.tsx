import { useState, useCallback, useEffect, useMemo } from "react";
import { Board } from "./components/Board";
import { ControlPanel } from "./components/ControlPanel";
import { WinrateBar } from "./components/WinrateBar";
import { ReviewPanel } from "./components/ReviewPanel";
import { api, forceMode } from "./ai/apiClient";
import { needsBackendConfig } from "./config";
import { BLACK, WHITE, GoBoard } from "./game/goEngine";
import type {
  GameState,
  PlayResponse,
  NewGameRequest,
  Player,
  CandidateMove,
  EngineStatus,
  MoveInfo,
  Difficulty,
  ReviewData,
} from "./types";

const DEFAULT_KOMI = 7.5;
const DEFAULT_DIFFICULTY: Difficulty = "medium";

export default function App() {
  const [game, setGame] = useState<GameState | null>(null);
  const [engineInfo, setEngineInfo] = useState<EngineStatus | null>(null);
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCandidates, setShowCandidates] = useState(true);
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [winrate, setWinrate] = useState<number>(0.5);
  const [backendMissing, setBackendMissing] = useState(false);
  const [candidates, setCandidates] = useState<CandidateMove[]>([]);
  const [scoreLead, setScoreLead] = useState<number | null>(null);
  const [lastMove, setLastMove] = useState<MoveInfo | null>(null);
  const [config, setConfig] = useState({
    boardSize: 19,
    komi: DEFAULT_KOMI,
    playerColor: "black" as Player,
    difficulty: DEFAULT_DIFFICULTY,
  });
  // 复盘模式
  const [reviewData, setReviewData] = useState<ReviewData | null>(null);
  const [reviewStep, setReviewStep] = useState(0);

  useEffect(() => {
    // 周期检测：用户在「服务器设置」填完地址后自动清除提示
    // 但在「本地 AI 模式」下不需要任何后端配置，直接隐藏提示
    const check = () => {
      try {
        const v = localStorage.getItem("weiqi_use_local_ai");
        if (v === "1") {
          setBackendMissing(false);
          return;
        }
      } catch { /* ignore */ }
      setBackendMissing(needsBackendConfig());
    };
    check();
    const iv = setInterval(check, 1500);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    api.engineStatus().then(setEngineInfo).catch(() => {});
  }, []);

  // Pull fresh analysis (winrate + candidates) for the human's current turn.
  const refreshAnalysis = useCallback(async (gameId: string) => {
    try {
      const a = await api.analyze(gameId);
      setWinrate(a.winrate);
      setScoreLead(a.score_lead);
      setCandidates(a.candidates);
    } catch {
      /* analysis optional */
    }
  }, []);

  const applyResponse = useCallback((resp: PlayResponse) => {
    if (!resp.ok) {
      setError(resp.illegal_reason || "非法走子");
      return;
    }
    setError(null);
    setGame((g) =>
      g
        ? {
            ...g,
            board: resp.board,
            to_move: resp.to_move,
            captures: resp.captures,
            finished: resp.finished,
            score: resp.score ?? null,
          }
        : g
    );
    // AI 主动认输提示：用 AI 自己的胜率（ai_winrate）展示
    if (resp.ai_resigned) {
      setError(`AI 已认输（胜率 ${((resp.ai_winrate ?? 0) * 100).toFixed(1)}%），对局结束`);
    }
    // Most recent move = AI move if present, else the human's last move.
    setLastMove(resp.ai_move ?? resp.last_move ?? null);
    // 前端显示的胜率：始终用玩家视角的 resp.winrate
    // (AI 走子后，后端已把 AI 视角翻转为玩家视角存到 winrate 字段)
    if (resp.winrate != null) setWinrate(resp.winrate);
    if (resp.score_lead != null) setScoreLead(resp.score_lead);
    setCandidates(resp.candidates || []);
  }, []);

  const startGame = useCallback(async () => {
    setError(null);
    // 本地 AI 模式直接开始，不检查后端地址
    try {
      const v = localStorage.getItem("weiqi_use_local_ai");
      const mode = v === "1" ? "local" : v === "0" ? "remote" : "auto";
      if (mode === "local") {
        setBackendMissing(false);
      } else if (needsBackendConfig()) {
        setBackendMissing(true);
        setError("请先在「服务器设置」中填写后端地址，如 http://192.168.1.100:8000，或切换为「本地内置 AI」模式");
        return;
      }
    } catch {
      if (needsBackendConfig()) {
        setBackendMissing(true);
        return;
      }
    }
    setThinking(false);
    setLastMove(null);
    setCandidates([]);
    setWinrate(0.5);
    setScoreLead(null);
    try {
      const req: NewGameRequest = {
        board_size: config.boardSize,
        komi: config.komi,
        player_color: config.playerColor,
        ai_difficulty: config.difficulty,
      };
      const state = await api.newGame(req);
      setGame(state);
      // If AI moves first (human is white), trigger AI now.
      if (state.to_move !== config.playerColor) {
        setThinking(true);
        try {
          const resp = await api.aiMove(state.game_id);
          applyResponse(resp);
          if (resp.ok && !resp.finished) await refreshAnalysis(state.game_id);
        } finally {
          setThinking(false);
        }
      } else {
        await refreshAnalysis(state.game_id);
      }
    } catch (e) {
      setError(`无法开始游戏: ${(e as Error).message}`);
    }
  }, [config, applyResponse, refreshAnalysis]);

  const onPlay = useCallback(
    async (x: number, y: number) => {
      if (!game || thinking || game.finished) return;
      if (game.to_move !== config.playerColor) return;
      setError(null);
      const color = config.playerColor === "black" ? BLACK : WHITE;
      // 用前端规则引擎做乐观更新，正确处理提子，避免服务器响应前显示残留死子
      const opt = GoBoard.fromGrid(game.board_size, game.board, game.captures);
      const placeResult = opt.place(x, y, color);
      if (!placeResult.ok) {
        setError(`非法走子: ${placeResult.reason}`);
        return;
      }
      setGame((g) =>
        g
          ? {
              ...g,
              board: opt.grid.map((r) => [...r]),
              captures: { ...opt.captures },
              to_move: config.playerColor === "black" ? "white" : "black",
            }
          : g
      );
      setLastMove({ x, y, color: config.playerColor });
      setThinking(true);
      try {
        const resp = await api.play(game.game_id, x, y);
        applyResponse(resp);
        // play 端点不再同步做 AI 分析；若 ai_pending，单独请求 ai_move
        if (resp.ok && !resp.finished && resp.ai_pending) {
          try {
            const aiResp = await api.aiMove(game.game_id);
            applyResponse(aiResp);
          } catch (aiErr) {
            setError(`AI 应手失败: ${(aiErr as Error).message}`);
          }
        }
        if (resp.ok && !resp.finished && resp.to_move === config.playerColor) {
          await refreshAnalysis(game.game_id);
        }
      } catch (e) {
        setError(`落子失败: ${(e as Error).message}`);
        const fresh = await api.state(game.game_id).catch(() => null);
        if (fresh) setGame(fresh);
      } finally {
        setThinking(false);
      }
    },
    [game, thinking, config.playerColor, applyResponse, refreshAnalysis]
  );

  const onPass = useCallback(async () => {
    if (!game || thinking || game.finished) return;
    if (game.to_move !== config.playerColor) return;
    setThinking(true);
    try {
      const resp = await api.play(game.game_id, null, null, { pass: true });
      applyResponse(resp);
      if (resp.ok && !resp.finished && resp.ai_pending) {
        try {
          const aiResp = await api.aiMove(game.game_id);
          applyResponse(aiResp);
        } catch (aiErr) {
          setError(`AI 应手失败: ${(aiErr as Error).message}`);
        }
      }
      if (resp.ok && !resp.finished && resp.to_move === config.playerColor) {
        await refreshAnalysis(game.game_id);
      }
    } catch (e) {
      setError(`弃权失败: ${(e as Error).message}`);
    } finally {
      setThinking(false);
    }
  }, [game, thinking, config.playerColor, applyResponse, refreshAnalysis]);

  const onUndo = useCallback(async () => {
    if (!game || thinking) return;
    setThinking(true);
    try {
      const resp = await api.undo(game.game_id);
      applyResponse(resp);
      if (resp.ok) await refreshAnalysis(game.game_id);
    } catch (e) {
      setError(`悔棋失败: ${(e as Error).message}`);
    } finally {
      setThinking(false);
    }
  }, [game, thinking, applyResponse, refreshAnalysis]);

  const onResign = useCallback(async () => {
    if (!game || thinking || game.finished) return;
    if (!confirm("确认认输?")) return;
    setThinking(true);
    try {
      const resp = await api.play(game.game_id, null, null, { resign: true });
      applyResponse(resp);
    } catch (e) {
      setError(`认输失败: ${(e as Error).message}`);
    } finally {
      setThinking(false);
    }
  }, [game, thinking, applyResponse]);

  // 进入复盘：拉取复盘数据，定位到最后一步
  const enterReview = useCallback(async () => {
    if (!game) return;
    try {
      const data = await api.review(game.game_id);
      setReviewData(data);
      setReviewStep(data.entries.length);
    } catch (e) {
      setError(`复盘加载失败: ${(e as Error).message}`);
    }
  }, [game]);

  const exitReview = useCallback(() => {
    setReviewData(null);
    setReviewStep(0);
  }, []);

  // 复盘模式：根据 reviewStep 用前端引擎重放重建棋盘
  const reviewBoard = useMemo(() => {
    if (!reviewData) return null;
    const b = new GoBoard(reviewData.board_size);
    for (let i = 0; i < reviewStep && i < reviewData.entries.length; i++) {
      const e = reviewData.entries[i];
      const color = e.color === "black" ? BLACK : WHITE;
      if (e.move) {
        b.place(e.move[0], e.move[1], color);
      } else {
        b.pass(color);
      }
    }
    return b;
  }, [reviewData, reviewStep]);

  // 复盘当前步的候选点和最佳应手
  const reviewCandidates = useMemo<CandidateMove[]>(() => {
    if (!reviewData || reviewStep === 0) return [];
    const e = reviewData.entries[reviewStep - 1];
    if (!e) return [];
    return e.candidates.map((c) => ({
      x: c.x, y: c.y, winrate: c.winrate,
      visits: c.visits, score_lead: c.score_lead, prior: c.prior,
    }));
  }, [reviewData, reviewStep]);

  const reviewLastMove = useMemo<MoveInfo | null>(() => {
    if (!reviewData || reviewStep === 0) return null;
    const e = reviewData.entries[reviewStep - 1];
    if (!e || !e.move) return null;
    return { x: e.move[0], y: e.move[1], color: e.color };
  }, [reviewData, reviewStep]);

  const reviewWinrate = useMemo(() => {
    if (!reviewData || reviewStep === 0) return 0.5;
    const e = reviewData.entries[reviewStep - 1];
    if (!e || e.post_winrate == null) return 0.5;
    // 后端 ReviewEntry.post_winrate = 该步走子方 (entry.color) 视角的胜率；
    // WinrateBar 始终需要「玩家视角」的胜率（与对局模式 resp.winrate 语义一致），
    // 因此如果该步是 AI 走子，要把 AI 视角翻转为玩家视角。
    const humanColor = reviewData.human_color ?? config.playerColor;
    return e.color === humanColor ? e.post_winrate : 1 - e.post_winrate;
  }, [reviewData, reviewStep, config.playerColor]);

  const humanColor = config.playerColor === "black" ? BLACK : WHITE;
  const aiTurn = game ? game.to_move !== config.playerColor : false;

  return (
    <div className="app">
      <div className="board-area">
        <div className="status-bar">
          <span className={`turn-indicator ${reviewData ? "black" : game?.to_move || "black"}`} aria-hidden />
          <span>
            {reviewData
              ? `复盘 — 第 ${reviewStep} / ${reviewData.entries.length} 手`
              : game
              ? game.finished
                ? `对局结束 — ${
                    game.score?.winner === "draw"
                      ? "平局"
                      : game.score?.winner === "black"
                      ? "黑胜"
                      : "白胜"
                  }`
                : thinking
                ? "AI 思考中…"
                : aiTurn
                ? "AI 回合"
                : "你的回合"
              : "未开始"}
          </span>
          {reviewData ? (
            <button className="link-btn" style={{ marginLeft: "auto" }} onClick={exitReview}>
              退出复盘
            </button>
          ) : game && (
            <span style={{ marginLeft: "auto", color: "var(--text-dim)" }}>
              提子 黑:{game.captures.black} 白:{game.captures.white}
              {scoreLead != null &&
                ` · 目差 ${scoreLead >= 0 ? "+" : ""}${scoreLead.toFixed(1)}`}
              {game.finished && (
                <button className="link-btn" style={{ marginLeft: 8 }} onClick={enterReview}>
                  复盘
                </button>
              )}
            </span>
          )}
        </div>

        <div className="board-wrap">
          {reviewData && reviewBoard ? (
            <Board
              size={reviewData.board_size}
              grid={reviewBoard.grid}
              lastMove={reviewLastMove}
              candidates={reviewCandidates}
              showCandidates={showCandidates}
              showWinrateHeatmap={false}
              thinking={false}
              onPlay={() => {}}
              hoverColor={BLACK}
              disabled
            />
          ) : game ? (
            <Board
              size={game.board_size}
              grid={game.board}
              lastMove={lastMove}
              candidates={candidates}
              showCandidates={showCandidates}
              showWinrateHeatmap={showHeatmap}
              thinking={thinking}
              onPlay={onPlay}
              hoverColor={humanColor}
              disabled={aiTurn || thinking || game.finished}
            />
          ) : (
            <div style={{ color: "var(--text-dim)" }}>点击右侧"开始对局"</div>
          )}
        </div>

        {reviewData ? (
          <WinrateBar winrate={reviewWinrate} perspective={config.playerColor} />
        ) : (
          game && <WinrateBar winrate={winrate} perspective={config.playerColor} />
        )}
        {backendMissing && !game && (
          <div style={{
            background: "var(--accent-dim)",
            border: "2px solid var(--accent)",
            borderRadius: 8,
            padding: "12px 16px",
            margin: "10px 0",
            fontSize: "0.95em",
            lineHeight: 1.6,
          }}>
            <strong style={{ color: "var(--accent)", display: "block", marginBottom: 6 }}>⚠️ 需要配置后端地址或启用本地 AI</strong>
            <div>当前为「远程后端」模式（Auto 检测未发现后端），请选择其一：</div>
            <div style={{ marginTop: 8, fontSize: "0.92em", color: "var(--text-dim)" }}>
              <strong>方案 A（推荐，无需电脑）</strong>：切换为 <strong>「本地内置 AI」</strong>，直接在手机/WebView 内运行 MCTS，不依赖任何后端。
              <button
                style={{ marginLeft: 10, padding: "4px 10px" }}
                onClick={() => { forceMode("local"); setBackendMissing(false); }}
              >启用本地 AI</button>
              <br/>
              <strong>方案 B（连电脑，更强 AI）</strong>：
              <br/>1. 确保手机和电脑在同一 WiFi
              <br/>2. 右侧「服务器设置」填写电脑 IP，如 <code>http://192.168.1.100:8000</code>
              <br/>3. 电脑启动后端：<code>python -m uvicorn app.main:app --host 0.0.0.0</code>
            </div>
          </div>
        )}
        {error && <div className="error-msg">{error}</div>}
      </div>

      {reviewData ? (
        <ReviewPanel
          data={reviewData}
          step={reviewStep}
          humanColor={reviewData.human_color ?? config.playerColor}
          onStepChange={setReviewStep}
        />
      ) : (
        <ControlPanel
          game={game}
          engineInfo={engineInfo}
          config={config}
          onConfigChange={setConfig}
          onStart={startGame}
          onPass={onPass}
          onUndo={onUndo}
          onResign={onResign}
          candidates={candidates}
          showCandidates={showCandidates}
          showHeatmap={showHeatmap}
          onToggleCandidates={() => setShowCandidates((v) => !v)}
          onToggleHeatmap={() => setShowHeatmap((v) => !v)}
          disabled={thinking || !game}
          winrate={winrate}
        />
      )}
    </div>
  );
}


