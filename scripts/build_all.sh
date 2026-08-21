#!/usr/bin/env bash
# ============================================================
# Weiqi AI — 一键构建脚本（exe + app）
#
# 用法:
#   ./scripts/build_all.sh            # 当前平台（PyInstaller 单文件）
#   ./scripts/build_all.sh --win      # Windows NSIS 安装包
#   ./scripts/build_all.sh --mac      # macOS DMG
#   ./scripts/build_all.sh --linux    # Linux AppImage
#
# 前置条件:
#   - Node.js + npm（前端 + Electron）
#   - Python 3.10+ + pip（后端 + PyInstaller）
#
# 输出:
#   backend/dist/WeiqiAI/     — PyInstaller 可执行文件（跨平台单文件）
#   desktop/release/          — Electron 安装包（exe/dmg/AppImage）
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
FRONTEND="$ROOT/frontend"
BACKEND="$ROOT/backend"
DESKTOP="$ROOT/desktop"

TARGET="${1:---auto}"

echo "============================================================"
echo "  围棋 AI — 桌面应用构建"
echo "  Target: $TARGET"
echo "============================================================"

# ---- Step 1: Build frontend ----
echo ""
echo ">> [1/4] 构建前端静态文件"
cd "$FRONTEND"
npm install --silent
npm run build
echo "   ✓ 前端构建完成: $FRONTEND/dist"

# ---- Step 2: Install backend deps + PyInstaller ----
echo ""
echo ">> [2/4] 安装后端依赖 + PyInstaller"
cd "$BACKEND"
pip install -q -r requirements.txt
pip install -q pyinstaller
echo "   ✓ 后端依赖就绪"

# ---- Step 3: PyInstaller 打包后端 ----
echo ""
echo ">> [3/4] PyInstaller 打包后端可执行文件"
WEIQI_FRONTEND_DIST="$FRONTEND/dist" pyinstaller weiqi.spec --noconfirm --clean 2>&1 | tail -5
echo "   ✓ 后端打包完成: $BACKEND/dist/WeiqiAI/"

# ---- Step 4: Electron 打包（可选）----
if [[ "$TARGET" == "--win" || "$TARGET" == "--mac" || "$TARGET" == "--linux" ]]; then
    echo ""
    echo ">> [4/4] Electron 打包: $TARGET"
    cd "$DESKTOP"
    npm install --silent
    npm run "dist:${TARGET#--}"
    echo "   ✓ Electron 包输出: $DESKTOP/release/"
    echo ""
    echo "============================================================"
    echo "  构建完成！"
    echo "  PyInstaller: $BACKEND/dist/WeiqiAI/"
    echo "  Electron:    $DESKTOP/release/"
    echo "============================================================"
else
    echo ""
    echo ">> [4/4] 跳过 Electron 打包（仅 PyInstaller 单文件模式）"
    echo ""
    echo "============================================================"
    echo "  构建完成！"
    echo "  可执行文件: $BACKEND/dist/WeiqiAI/WeiqiAI"
    echo ""
    echo "  如需 Electron 原生窗口安装包："
    echo "    Linux: ./scripts/build_all.sh --linux"
    echo "    Windows: ./scripts/build_all.sh --win  (需在 Windows 上运行)"
    echo "    macOS: ./scripts/build_all.sh --mac   (需在 macOS 上运行)"
    echo "============================================================"
fi
