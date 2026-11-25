#!/usr/bin/env bash
# Start backend (http://localhost:8000) and web dashboard (http://localhost:5173) together.
# Stop both with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ ! -d backend/.venv ]; then
  echo "Run setup first:  bash scripts/setup_mac.sh"; exit 1
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(
  cd "$ROOT/backend"
  source .venv/bin/activate
  # The live MJPEG stream never ends on its own, so without a timeout an auto-reload waits forever
  # for open browser tabs and the API hangs. 3 s is plenty for normal requests to finish.
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app --timeout-graceful-shutdown 3
) &

(
  cd "$ROOT/frontend"
  npm run dev
) &

sleep 3
echo ""
echo "  Dashboard:  the 'Local:' address Vite printed above (http://localhost:5173 unless that port was taken)"
echo "  API docs:   http://localhost:8000/docs"
echo ""
wait
