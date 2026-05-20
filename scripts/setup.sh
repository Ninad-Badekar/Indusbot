#!/usr/bin/env bash
# One-time setup: venv, dependencies, Piper TTS, Ollama models, .env
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PIPER_DIR="$ROOT/.local/piper"
PIPER_VERSION="1.2.0"
MODELS_DIR="$ROOT/models"

# ---- Prerequisites ----
echo "=== Checking prerequisites ==="
command -v python3 >/dev/null 2>&1 || { echo "python3 required"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl required"; exit 1; }

# ---- Virtual environment ----
echo "=== Setting up virtual environment ==="
if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
  echo "  Created $VENV"
else
  echo "  $VENV already exists"
fi

source "$VENV/bin/activate"
echo "  Upgrading pip..."
pip install --upgrade pip -q

echo "  Installing Python dependencies..."
pip install -r "$ROOT/backend/requirements.txt" -q

# ---- .env ----
echo "=== Environment configuration ==="
if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "  Created .env from .env.example"
  echo "  >>> Edit .env with your Twilio credentials and PUBLIC_BASE_URL <<<"
else
  echo "  .env already exists"
fi

# ---- Piper TTS binary ----
echo "=== Piper TTS ==="
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  PIPER_ARCH="x86_64" ;;
  aarch64) PIPER_ARCH="aarch64" ;;
  *)       echo "  Unsupported architecture: $ARCH"; exit 1 ;;
esac

if [[ ! -f "$PIPER_DIR/piper" ]]; then
  mkdir -p "$PIPER_DIR"
  PIPER_TAR="piper-${ARCH}-${PIPER_VERSION}.tar.gz"
  PIPER_URL="https://github.com/rhasspy/piper/releases/download/v${PIPER_VERSION}/${PIPER_TAR}"
  echo "  Downloading Piper binary ($PIPER_URL)..."
  curl -fL "$PIPER_URL" -o "/tmp/$PIPER_TAR"
  tar -xzf "/tmp/$PIPER_TAR" -C "$PIPER_DIR" --strip-components=1
  rm "/tmp/$PIPER_TAR"
  echo "  Installed Piper to $PIPER_DIR"
else
  echo "  Piper binary already present"
fi

# ---- Piper voice model ----
echo "=== Piper voice model ==="
if [[ ! -f "$MODELS_DIR/voice.onnx" ]]; then
  bash "$ROOT/scripts/download-piper-voice.sh"
else
  echo "  Voice model already present at $MODELS_DIR/voice.onnx"
fi

# ---- Ollama models ----
echo "=== Ollama models ==="
if command -v ollama >/dev/null 2>&1; then
  source "$ROOT/.env" 2>/dev/null || true
  OLLAMA_VOICE="${OLLAMA_VOICE_MODEL:-llama3.2:1b}"
  OLLAMA_CHAT="${OLLAMA_MODEL:-llama3.1:8b}"
  echo "  Pulling $OLLAMA_CHAT..."
  ollama pull "$OLLAMA_CHAT" 2>/dev/null || echo "  WARNING: ollama not reachable — run 'ollama serve' first and retry"
  echo "  Pulling $OLLAMA_VOICE..."
  ollama pull "$OLLAMA_VOICE" 2>/dev/null || true
else
  echo "  WARNING: ollama not found. Install from https://ollama.com"
  echo "  Then run: ollama pull llama3.1:8b && ollama pull llama3.2:1b"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "To start the server:"
echo "  source .venv/bin/activate"
echo "  PYTHONPATH=backend .venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo ""
echo "Or use the existing script:"
echo "  ./scripts/run-local.sh"
echo ""
echo "Remember to:"
echo "  1. Edit .env with your Twilio credentials"
echo "  2. Set PUBLIC_BASE_URL to your ngrok/HTTPS URL"
echo "  3. Start Ollama: ollama serve"
