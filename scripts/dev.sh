#!/usr/bin/env bash
# Start both backend (FastAPI) and frontend (Vite dev server) for local dev.
# Use Ctrl-C to stop both.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# Trap to kill child processes on exit.
trap 'kill 0' INT TERM EXIT

echo ">> Starting backend (uvicorn :8000)"
( cd "$ROOT/backend" && \
  python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload ) &

echo ">> Starting frontend (vite :5173)"
( cd "$ROOT/frontend" && npm run dev ) &

echo
echo ">> Open http://localhost:5173 in your browser."
echo ">> API docs at http://localhost:8000/docs"
wait
