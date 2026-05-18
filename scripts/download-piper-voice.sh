#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VOICE="${1:-en_US-lessac-medium}"
OUTPUT_DIR="${2:-$ROOT/models}"
OUTPUT_FILE="${OUTPUT_DIR}/voice.onnx"
CONFIG_FILE="${OUTPUT_DIR}/voice.onnx.json"

mkdir -p "$OUTPUT_DIR"

case "$VOICE" in
  en_US-lessac-medium)
    HF_PATH="en/en_US/lessac/medium/en_US-lessac-medium"
    ;;
  en_US-amy-medium)
    HF_PATH="en/en_US/amy/medium/en_US-amy-medium"
    ;;
  en_US-amy-low)
    HF_PATH="en/en_US/amy/low/en_US-amy-low"
    ;;
  en_GB-semrie-medium)
    HF_PATH="en/en_GB/semrie/medium/en_GB-semrie-medium"
    ;;
  *)
    echo "Unknown voice: $VOICE"
    echo "Available: en_US-lessac-medium, en_US-amy-medium, en_US-amy-low, en_GB-semrie-medium"
    exit 1
    ;;
esac

BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main"

echo "Downloading ${VOICE} model..."
curl -fL "${BASE_URL}/${HF_PATH}.onnx" -o "$OUTPUT_FILE"

echo "Downloading ${VOICE} config..."
curl -fL "${BASE_URL}/${HF_PATH}.onnx.json" -o "$CONFIG_FILE"

echo "Saved model to ${OUTPUT_FILE}"
echo "Saved config to ${CONFIG_FILE}"
