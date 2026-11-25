#!/usr/bin/env bash
# One-time setup on macOS (Apple Silicon or Intel).   Run:  bash scripts/setup_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "==> Smart CCTV setup in $ROOT"

# ---- Python 3.10+ ----
PY=""
for cand in python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "!! Python 3.10+ not found. Install it with:  brew install python@3.12   (Homebrew: https://brew.sh)"
  exit 1
fi
echo "==> Using $($PY --version)"

# ---- Node 18+ ----
if ! command -v npm >/dev/null 2>&1; then
  echo "!! Node.js not found. Install it with:  brew install node"
  exit 1
fi
echo "==> Using Node $(node --version)"

# ---- Backend ----
cd "$ROOT/backend"
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip >/dev/null
echo "==> Installing backend packages (PyTorch + YOLO can take a few minutes)..."
pip install -r requirements.txt

# ---- .env ----
cd "$ROOT"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Created .env from .env.example (edit it to add your camera URL and Telegram bot)"
fi

# ---- Frontend ----
cd "$ROOT/frontend"
echo "==> Installing web dashboard packages..."
npm install

echo ""
echo "Done. Start everything with:   bash scripts/dev.sh"
echo "Then open:                     http://localhost:5173"
