interface WinrateBarProps {
  winrate: number; // 0..1 from the perspective of the player to move
  perspective: "black" | "white"; // whose winrate to show as the "left" side
}

export function WinrateBar({ winrate, perspective }: WinrateBarProps) {
  // Convert to black's winrate for display
  const blackWinrate =
    perspective === "black" ? winrate : 1 - winrate;
  const blackPct = Math.round(blackWinrate * 100);
  const whitePct = 100 - blackPct;
  return (
    <div className="winrate-bar" title={`黑 ${blackPct}% / 白 ${whitePct}%`}>
      <div className="black-fill" style={{ width: `${blackPct}%` }} />
      <div className="label">
        <span style={{ color: "#fff" }}>黑 {blackPct}%</span>
        <span style={{ color: "#000" }}>白 {whitePct}%</span>
      </div>
    </div>
  );
}
