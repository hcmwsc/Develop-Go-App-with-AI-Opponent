"""Standalone launcher: starts the FastAPI backend and opens the browser.

Used by PyInstaller to create a single-executable desktop app.
The frontend static files are served by FastAPI itself (StaticFiles mount).
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _resolve_static_dir() -> Path | None:
    """定位前端 dist 目录（PyInstaller 打包后 / 开发环境）。"""
    candidates = [
        Path(sys._MEIPASS) / "static",               # PyInstaller onefile
        Path(sys._MEIPASS) / "frontend" / "dist",     # PyInstaller dir mode
        Path(__file__).resolve().parent.parent / "frontend" / "dist",  # dev
    ]
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return None


def _wait_and_open_browser(port: int, delay: float = 1.5) -> None:
    """等待后端就绪后自动打开浏览器。"""
    import urllib.request

    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{url}health", timeout=1)
            time.sleep(delay)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(0.3)
    print(f"[launcher] 后端未在 15s 内就绪，请手动打开 {url}")


def main() -> None:
    import uvicorn

    port = int(os.environ.get("WEIQI_PORT", "8000"))

    # 告诉 FastAPI 静态文件位置
    static_dir = _resolve_static_dir()
    if static_dir:
        os.environ["WEIQI_STATIC_DIR"] = str(static_dir)
        print(f"[launcher] 前端静态文件: {static_dir}")
    else:
        print("[launcher] 未找到前端静态文件，API-only 模式")

    # 后台线程：等待就绪后开浏览器
    t = threading.Thread(target=_wait_and_open_browser, args=(port,), daemon=True)
    t.start()

    print(f"[launcher] 启动后端 http://127.0.0.1:{port}")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
