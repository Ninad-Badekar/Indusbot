# Ava — Corporate Banking Voice Assistant

AI voice assistant that guides users through corporate bank account setup over the phone.

## Architecture

```
Caller → Twilio → Real-Time Transcriptions (STT webhook)
  → FAISS vector search → Ollama (voice: llama3.2:1b) → Piper TTS → WebSocket /stream → caller
```

## Prerequisites

- **Python 3.11+**
- **[Ollama](https://ollama.com/download)** (local LLM runtime)
- **PostgreSQL 16+** (conversation tables; created on startup)
- **[Twilio](https://twilio.com)** account with a voice-enabled phone number
- **curl** (for setup scripts)

## Quick Start

```bash
# 1. Clone and enter the project
cd Indusbot

# 2. One-time setup: venv, Piper, voice model, Ollama pulls
chmod +x scripts/*.sh
./scripts/setup-local.sh

# 3. Configure environment (if setup did not create it)
cp .env.example .env
# Edit .env: Twilio credentials, PUBLIC_BASE_URL (ngrok HTTPS URL)

# 4. Start Ollama (if not already running as a service)
ollama serve   # in another terminal, or use systemd

# 5. Run the backend
./scripts/run-local.sh
```

### PostgreSQL

Create the default database user (once):

```bash
sudo -u postgres psql -c "CREATE USER ava WITH PASSWORD 'ava';"
sudo -u postgres psql -c "CREATE DATABASE ava OWNER ava;"
```

Or set `DATABASE_URL` in `.env` to your existing Postgres instance.

## Local services

| Service | Port | How to run |
|---------|------|------------|
| Backend | `8000` | `./scripts/run-local.sh` |
| Ollama | `11434` | `ollama serve` (install via ollama.com) |
| PostgreSQL | `5432` | System package or existing instance |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/incoming-call` | POST | Twilio voice webhook, returns TwiML with Media Stream + transcription |
| `/transcription-callback` | POST | Twilio Real-Time Transcription utterances (STT) |
| `/stream` | WebSocket | Bidirectional media stream (Piper TTS outbound) |
| `/api/chat` | POST | Text-based chat (for testing) |
| `/health` | GET | Health check |

### Test with chat

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How do I open a corporate account?"}'
```

## Twilio Setup

1. Buy a Twilio phone number with voice capability
2. Enable **Real-Time Transcriptions** on your Twilio account
3. In Twilio Console → Phone Numbers → configure voice webhook:
   - **URL**: `https://your-public-url/incoming-call`
   - **Method**: HTTP POST
4. Set `PUBLIC_BASE_URL` in `.env` to your public HTTPS URL (required for transcription callbacks and the media stream WebSocket)
5. For local development, use [ngrok](https://ngrok.com):
   ```bash
   ngrok http 8000
   ```
   Then use the ngrok URL in Twilio's webhook config.

## Piper TTS

`setup-local.sh` installs the Piper binary under `.local/piper/` and downloads `en_US-lessac-medium` to `models/voice.onnx`.

To use a different voice:

```bash
./scripts/download-piper-voice.sh en_US-amy-medium ./models
# Set PIPER_VOICE_PATH=./models/voice.onnx in .env (or leave empty to use the default path)
```

## Ollama models

Voice calls use `llama3.2:1b` for low latency on CPU. Text chat uses `llama3`. Configure via `OLLAMA_MODEL` / `OLLAMA_VOICE_MODEL` in `.env`.

```bash
ollama pull llama3
ollama pull llama3.2:1b
```

(`setup-local.sh` runs these automatically if Ollama is installed.)

## Knowledge Base

Add `.md` files to `backend/knowledge_base/`. The RAG pipeline chunks on `##` headers and indexes them with FAISS. The index is rebuilt on every backend restart.

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Environment config
│   │   ├── routers/             # Twilio webhooks, stream, chat
│   │   ├── services/            # RAG, LLM, TTS, voice pipeline
│   │   └── db/                  # SQLAlchemy models
│   ├── knowledge_base/          # Markdown files for RAG
│   └── requirements.txt
├── models/                      # Piper voice (created by setup)
├── .local/piper/                # Piper binary (created by setup)
├── scripts/
│   ├── setup-local.sh           # One-time local setup
│   ├── run-local.sh             # Start uvicorn
│   └── download-piper-voice.sh  # Download alternative voices
├── .env.example
└── .agents/                     # Agent prompt files
```

## Troubleshooting

- **`.env` still points at Docker** (`ollama`, `postgres` hostnames): copy values from `.env.example` (`localhost`).
- **Piper not found**: ensure `setup-local.sh` completed; `run-local.sh` adds `.local/piper` to `PATH`.
- **Ollama connection refused**: run `ollama serve` and check `OLLAMA_BASE_URL=http://localhost:11434`.
- **Postgres connection failed**: create the `ava` user/database (see above) or update `DATABASE_URL`.
