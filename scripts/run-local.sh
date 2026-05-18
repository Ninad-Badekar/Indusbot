#!/usr/bin/env bash
# Run the FastAPI backend locally (no Docker).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$ROOT/.venv"
PIPER_DIR="$ROOT/.local/piper"

if [[ ! -d "$VENV" ]]; then
  echo "Virtualenv not found. Run ./scripts/setup-local.sh first."
  exit 1
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo ".env not found. Run ./scripts/setup-local.sh or cp .env.example .env"
  exit 1
fi

export PATH="$PIPER_DIR:$PATH"

# shellcheck source=/dev/null
source "$VENV/bin/activate"
cd "$BACKEND"

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload "$@"
