# Ava — Corporate Banking Voice Assistant

AI voice assistant that guides users through corporate bank account setup over the phone.

## Architecture

```
Caller → Twilio → Real-Time Transcriptions (STT webhook)
  → knowledge base step lookup → Intent Classifier (hybrid)
  → Step KB response / LLM fallback → Piper TTS (cached) → WebSocket /stream → caller
```

**Processing flow:**
1. Twilio sends user speech via transcription callback
2. Voice pipeline resolves current step from KB index (direct step lookup, no embedding search for numbered steps)
3. Intent classifier determines user intent (confirm/repeat/confused/off_topic) using a hybrid approach
4. For steps 1–8, KB responses are served directly (zero hallucination, pre-cached in TTS)
5. Piper TTS streams audio back through Twilio's WebSocket media stream

## Prerequisites

- **Python 3.11+**
- **[Ollama](https://ollama.com/download)** (local LLM runtime)
- **[Twilio](https://twilio.com)** account with a voice-enabled phone number
- **curl** (for setup scripts)
- **CPU only** (no GPU required; all inference runs on CPU)

## Quick Start

```bash
# 1. One-time setup (venv, dependencies, Piper TTS, Ollama models, .env)
chmod +x scripts/*.sh
./scripts/setup.sh

# 2. Edit .env with your Twilio credentials and PUBLIC_BASE_URL (ngrok HTTPS URL)

# 3. Start Ollama (if not already running as a service)
ollama serve   # in another terminal, or use systemd

# 4. Run the backend
PYTHONPATH=backend .venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Local services

| Service | Port | How to run |
|---------|------|------------|
| Backend | `8000` | `PYTHONPATH=backend .venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Ollama | `11434` | `ollama serve` (install via ollama.com) |

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

Make a test call:

```bash
curl -X POST http://localhost:8000/incoming-call \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=test123&From=%2B15551234567"
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

`setup.sh` installs the Piper binary under `.local/piper/` and downloads `en_US-lessac-medium` to `models/voice.onnx`.

**Pre-caching:** At startup, all 13 unique KB step responses + 3 goodbye sentences are pre-synthesised and cached in an in-memory dict (`_tts_cache`). This adds ~195s to startup time on CPU but makes every response during a call instant (< 100ms).

To use a different voice:

```bash
./scripts/download-piper-voice.sh en_US-amy-medium ./models
# Set PIPER_VOICE_PATH=./models/voice.onnx in .env (or leave empty to use the default path)
```

## Ollama models

Configured via `OLLAMA_MODEL` / `OLLAMA_VOICE_MODEL` in `.env`:

| Model | Used for | Typical latency (CPU) |
|-------|----------|-----------------------|
| `llama3.1:8b` | Text chat responses, intent classification for ambiguous utterances | 2–3s per short-prompt inference |
| `llama3.2:1b` | Voice response streaming (when LLM fallback is needed) | 0.5–3s per token generation |

Pull them:

```bash
ollama pull llama3.1:8b
ollama pull llama3.2:1b
```

(`setup.sh` runs these automatically if Ollama is installed.)

## Intent Classification (Hybrid LLM + Regex)

User intent is determined through a multi-stage pipeline, from fastest to slowest:

1. **Fast-path keyword sets** (0ms) — exact-match against `_CONFIRM_WORDS` (done, yes, proceed, i did, etc.) and `_REPEAT_WORDS` (repeat, help, wait, etc.). Handles ~80% of utterances instantly.

2. **LLM-based classification** (2–3s) — for non-obvious utterances, a short prompt (`Step N: ...\nUser: ...\nIntent:`) is sent to `llama3.1:8b` with a 5s timeout. Output is post-processed via keyword matching.

3. **Regex fallback** (instant) — if the LLM times out or returns garbage, a comprehensive regex pipeline checks for confirmation (with negation awareness), repeat requests, confusion indicators, and off-topic queries in that order.

4. **Negation detection** — patterns like "haven't done", "not yet", "cannot proceed" are stripped before confirmation keywords are checked, preventing false step advances on "I haven't done that yet" while allowing "I haven't done that but I want to proceed" (mixed affirmations work correctly).

All results are cached by `step||text` key, so repeated utterances are instant.

## Knowledge Base

KB files live in `backend/knowledge_base/`. The RAG pipeline chunks on `##` headers and indexes them with FAISS. However, **numbered steps 1–8 are resolved directly** via `get_step_content()` from a pre-built dict mapping step numbers to chunks — no embedding search is used for the core step flow, eliminating hallucination risk.

The embedding search (`search()`) is only used as a fallback when a step chunk is not found, or for non-step queries.

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # Environment config (ollama_model, ollama_voice_model, etc.)
│   │   ├── conversation_log.py  # Speech logging to /tmp
│   │   ├── debug_log.py         # Hypothesis-driven debug logging
│   │   ├── routers/
│   │   │   ├── calls.py         # Twilio voice webhook (TwiML)
│   │   │   ├── transcription.py # STT callback + confidence filtering (>= 0.9)
│   │   │   ├── stream.py        # WebSocket media stream for Piper outbound
│   │   │   └── chat.py          # Text chat endpoint
│   │   ├── services/
│   │   │   ├── voice_pipeline.py # Main orchestration: intent → response → TTS
│   │   │   ├── llm.py           # classify_intent(), stream_voice_sentences(), warmup()
│   │   │   ├── memory.py        # SessionMemory: step tracking, confirmation regex, negation
│   │   │   ├── retrieval.py     # get_step_content(), extract_step_responses(), search() (FAISS)
│   │   │   ├── tts.py           # Piper TTS synthesis + _tts_cache
│   │   │   └── voice_outbound.py # WebSocket streaming helper
│   │   └── db/                  # SQLAlchemy models (conversation logging)
│   ├── knowledge_base/
│   │   └── indusdirect_setup.md # Step-by-step guide (source of truth)
│   └── requirements.txt
├── models/                      # Piper voice onnx model (created by setup)
├── .local/piper/                # Piper binary + espeak-ng-data (created by setup)
├── scripts/
│   ├── setup.sh                 # One-time setup (venv, deps, Piper, Ollama)
│   ├── run-local.sh             # Start uvicorn
│   └── download-piper-voice.sh  # Download alternative voices
├── .env                         # Local config (not committed)
└── .env.example
```

## Troubleshooting

- **`.env` still points at Docker** (`ollama`, `postgres` hostnames): copy values from `.env.example` (`localhost`).
- **Piper not found**: ensure `setup.sh` completed; `run-local.sh` adds `.local/piper` to `PATH`.
- **Ollama connection refused**: run `ollama serve` and check `OLLAMA_BASE_URL=http://localhost:11434`.
- **Uvicorn fails with "No module named 'app'"**: start with `PYTHONPATH=backend` set, or use `./scripts/run-local.sh`.
- **Call ends before bot responds**: the 8B LLM takes 2–3s per inference on CPU. If the call timeout is too short, the transcription arrives after the stream closes. Ensure `CLASSIFY_TIMEOUT` (5s default) is less than the call's silence timeout.
- **Transcription confidence < 0.9**: transcriptions below 0.9 are filtered out. Adjust `_CONFIDENCE_THRESHOLD` in `transcription.py` if needed.
