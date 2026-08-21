#!/usr/bin/env bash
# Build script for Windows exe & multi-platform archives.
#
#   1. 把前端 dist 拷贝到 launcher/frontend_dist
#   2. 把后端源码拷贝到 launcher/backend_src（只含必需项）
#   3. CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -> WeiqiAI.exe
#   4. 同时构建 Linux / macOS 版本
#   5. 组装发布包到 dist_apk/
#
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LAUNCHER="$ROOT/desktop/launcher"
FRONTEND_DIST="$ROOT/frontend/dist"
BACKEND_SRC="$ROOT/backend"
OUT_DIR="$ROOT/frontend/dist_apk"
VERSION="0.1.0"

mkdir -p "$OUT_DIR"

# ---------------- Step 1: sync frontend dist ----------------
echo ">> [1/5] 同步前端 dist 到 launcher/frontend_dist"
rm -rf "$LAUNCHER/frontend_dist"
cp -r "$FRONTEND_DIST" "$LAUNCHER/frontend_dist"

# ---------------- Step 2: sync backend source ----------------
echo ">> [2/5] 同步后端源码到 launcher/backend_src"
rm -rf "$LAUNCHER/backend_src"
mkdir -p "$LAUNCHER/backend_src"
cp -r "$BACKEND_SRC/app" "$LAUNCHER/backend_src/"
cp "$BACKEND_SRC/requirements.txt" "$LAUNCHER/backend_src/"
cp "$BACKEND_SRC/main.py" "$LAUNCHER/backend_src/" 2>/dev/null || true
# Add a sentinel so the Go launcher knows this tree has been extracted.
echo "marker: weiqi backend $(date +%s)" > "$LAUNCHER/backend_src/placeholder.txt"

# ---------------- Step 3: build binaries ----------------
echo ">> [3/5] 交叉编译 Go 启动器"

build_for() {
    local goos="$1" goarch="$2" ext="$3"
    local tag="WeiqiAI-${VERSION}-${goos}-${goarch}"
    local out_dir="$OUT_DIR/$tag"
    mkdir -p "$out_dir"
    local bin_name="WeiqiAI${ext}"
    (
        cd "$LAUNCHER"
        CGO_ENABLED=0 GOOS="$goos" GOARCH="$goarch" \
            go build -ldflags="-s -w" -o "$out_dir/$bin_name" .
    )
    echo "   ✓ $goos/$goarch -> $out_dir/$bin_name"
    echo "$tag" > "$out_dir/.tag"
}

build_for "windows" "amd64" ".exe"
build_for "linux" "amd64" ""
build_for "darwin" "amd64" ""
build_for "darwin" "arm64" ""

# ---------------- Step 4: assemble archives ----------------
echo ">> [4/5] 组装发布包"

make_readme() {
    local out="$1" bin="$2"
    cat > "$out" <<EOF
围棋 AI v${VERSION} — 使用说明
========================

1. 确保已经安装 Python 3.10+（推荐 3.12）。
   - Windows: https://www.python.org/downloads/ （安装时勾选 Add to PATH）
   - macOS:   brew install python@3.12
   - Linux:   sudo apt install python3.12 python3-pip

2. 双击运行 ${bin}
   - 首次启动会自动创建虚拟环境并安装依赖，耗时约 1-3 分钟。
   - 浏览器会自动打开 http://127.0.0.1:8000/
   - 关闭命令行窗口即可退出。

3. 若自动打开浏览器失败，可手动访问:
   http://127.0.0.1:8000/

源代码 / Bug 反馈: 项目仓库
EOF
}

for tag_dir in "$OUT_DIR"/WeiqiAI-*-*/; do
    tag="$(basename "$tag_dir")"
    # Skip this marker dir (our own dist_apk parent would recurse).
    if [[ "$tag" == ".zip" || "$tag" == ".tar" ]]; then
        continue
    fi
    bin="WeiqiAI"
    if [[ "$tag" == *windows* ]]; then
        bin="WeiqiAI.exe"
    fi
    make_readme "$tag_dir/README.txt" "$bin"
    chmod +x "$tag_dir/$bin" 2>/dev/null || true

    # Create archive.
    cd "$OUT_DIR"
    archive_base="${tag}"
    if [[ "$tag" == *windows* ]]; then
        zip -rq "${archive_base}.zip" "$tag"
        echo "   ✓ 已创建 Windows 压缩包: $OUT_DIR/${archive_base}.zip"
    elif [[ "$tag" == *darwin* ]]; then
        tar -czf "${archive_base}.tar.gz" "$tag"
        echo "   ✓ 已创建 macOS 压缩包: $OUT_DIR/${archive_base}.tar.gz"
    else
        tar -czf "${archive_base}.tar.gz" "$tag"
        echo "   ✓ 已创建 Linux 压缩包: $OUT_DIR/${archive_base}.tar.gz"
    fi
    cd "$ROOT"
done

# ---------------- Step 5: summary ----------------
echo ""
echo ">> [5/5] 产物清单"
ls -lhS "$OUT_DIR" 2>/dev/null | tail -n +2

echo ""
echo "构建完成！"
