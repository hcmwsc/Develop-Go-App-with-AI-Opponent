"""Application configuration.

Environment variables override defaults. KataGo is optional; if its binary
or model path is not configured, the AI manager falls back to the built-in
MCTS engine.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Settings:
    # Server
    host: str = os.getenv("GO_HOST", "127.0.0.1")
    port: int = int(os.getenv("GO_PORT", "8000"))
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv(
            "GO_CORS_ORIGINS", "http://localhost:5173,http://localhost:4173"
        ).split(",")
    )

    # Default board
    default_board_size: int = int(os.getenv("GO_BOARD_SIZE", "19"))

    # AI engine selection: "auto" | "mcts" | "katago"
    ai_engine: str = os.getenv("GO_AI_ENGINE", "auto")

    # MCTS
    mcts_simulations: int = int(os.getenv("GO_MCTS_SIMS", "200"))
    mcts_exploration: float = float(os.getenv("GO_MCTS_C", "1.4"))

    # KataGo (optional)
    katago_binary: Optional[str] = os.getenv("KATAGO_BINARY")
    katago_model: Optional[str] = os.getenv("KATAGO_MODEL")
    katago_config: Optional[str] = os.getenv("KATAGO_CONFIG")
    katago_analysis_threads: int = int(os.getenv("KATAGO_THREADS", "2"))


settings = Settings()
