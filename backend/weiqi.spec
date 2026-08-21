# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Weiqi AI desktop app.

Build:
    cd backend
    pyinstaller weiqi.spec

Output:
    dist/WeiqiAI/          (目录模式, 跨平台)
    dist/WeiqiAI.exe       (Windows 单文件)
"""

import os
import sys
from pathlib import Path

block_cipher = None

# 定位前端 dist
_frontend_dist = Path(os.environ.get("WEIQI_FRONTEND_DIST", "../frontend/dist")).resolve()

# 收集数据文件
datas = []
if _frontend_dist.exists():
    datas.append((str(_frontend_dist), "frontend/dist"))

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "app.main",
        "app.config",
        "app.api.routes_game",
        "app.api.routes_ai",
        "app.services.game_service",
        "app.ai.mcts",
        "app.ai.manager",
        "app.core.board",
        "app.core.rules",
        "app.models.schemas",
    ],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PIL", "IPython", "jupyter"],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WeiqiAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 保留控制台以便查看日志
    icon=None,  # TODO: 添加 icon.ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WeiqiAI",
)
