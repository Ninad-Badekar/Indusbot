import asyncio
import audioop
import base64
import json
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.services.call_registry import call_registry
from app.services.memory import session_memory
from app.services.tts import get_cached_greeting
from app.services.voice_outbound import send_ulaw_audio
from app.services.voice_pipeline import try_process_utterance

logger = logging.getLogger(__name__)
router = APIRouter()

MIN_AUDIO_BYTES = 12000
SILENCE_SECONDS = settings.voice_silence_seconds
MAX_AUDIO_BYTES = 48000
SPEECH_RMS_THRESHOLD = 600
MIN_SPEECH_CHUNKS = 12


def _chunk_has_speech(chunk: bytes) -> bool:
    if not chunk:
        return False
    pcm = audioop.ulaw2lin(chunk, 2)
    return audioop.rms(pcm, 2) >= SPEECH_RMS_THRESHOLD


@router.websocket("/stream")
async def audio_stream(websocket: WebSocket):
    session_id = websocket.query_params.get("session_id", str(uuid.uuid4()))
    await websocket.accept()
    logger.info("WebSocket connected session=%s stt=%s", session_id, settings.stt_provider)

    stream_sid: str | None = None
    call_sid: str | None = None
    call_active = True
    debounce_task: asyncio.Task | None = None

    def is_active() -> bool:
        return call_active

    # Whisper-only state
    audio_buffer = bytearray()
    last_buffer_growth_at = 0.0
    speech_chunks = 0

    async def process_whisper_utterance():
        nonlocal audio_buffer, speech_chunks

        if not call_active or len(audio_buffer) < MIN_AUDIO_BYTES:
            return

        if session_memory.is_bot_speaking(session_id):
            logger.info("[%s] Skipping utterance — bot is speaking", session_id[:8])
            audio_buffer.clear()
            speech_chunks = 0
            return

        audio_bytes = bytes(audio_buffer)
        audio_buffer.clear()
        speech_chunks = 0

        t0 = time.monotonic()
        from app.services.stt import transcribe_voice_audio

        user_text = await asyncio.to_thread(transcribe_voice_audio, audio_bytes)
        stt_ms = int((time.monotonic() - t0) * 1000)

        if not user_text.strip():
            logger.info("Empty transcription, skipping (stt_ms=%d)", stt_ms)
            return

        await try_process_utterance(
            session_id=session_id,
            user_text=user_text,
            call_sid=call_sid,
            stt_ms=stt_ms,
        )

    async def debounced_process():
        try:
            while call_active:
                await asyncio.sleep(SILENCE_SECONDS)
                silent_for = time.monotonic() - last_buffer_growth_at
                if silent_for >= SILENCE_SECONDS - 0.05:
                    logger.info(
                        "Silence detected (%.0fms), processing utterance",
                        silent_for * 1000,
                    )
                    await process_whisper_utterance()
                    return
        except asyncio.CancelledError:
            pass

    def schedule_processing():
        nonlocal debounce_task
        if debounce_task and not debounce_task.done():
            return
        debounce_task = asyncio.create_task(debounced_process())

    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event = data.get("event")

            if event == "start":
                stream_sid = data.get("streamSid") or data.get("start", {}).get("streamSid")
                start_data = data.get("start", {})
                custom = start_data.get("customParameters") or {}
                if custom.get("session_id"):
                    session_id = custom["session_id"]
                call_sid = start_data.get("callSid") or call_sid

                if call_sid:
                    call_registry.attach_stream(
                        call_sid,
                        websocket,
                        stream_sid,
                        is_active,
                    )

                logger.info(
                    "Stream started stream_sid=%s call_sid=%s session=%s",
                    stream_sid,
                    call_sid,
                    session_id,
                )

                greeting_ulaw = get_cached_greeting()
                if greeting_ulaw and stream_sid:
                    await send_ulaw_audio(websocket, stream_sid, greeting_ulaw)

            elif event == "media" and settings.stt_provider == "whisper":
                chunk = base64.b64decode(data["media"]["payload"])
                if chunk:
                    audio_buffer.extend(chunk)
                    if _chunk_has_speech(chunk):
                        last_buffer_growth_at = time.monotonic()
                        speech_chunks += 1

                has_enough_speech = speech_chunks >= MIN_SPEECH_CHUNKS
                if len(audio_buffer) >= MAX_AUDIO_BYTES and has_enough_speech:
                    if debounce_task and not debounce_task.done():
                        debounce_task.cancel()
                    await process_whisper_utterance()
                elif len(audio_buffer) >= MIN_AUDIO_BYTES and has_enough_speech:
                    schedule_processing()

            elif event == "stop":
                logger.info("Stream stopped")
                call_active = False
                if settings.stt_provider == "whisper":
                    if debounce_task and not debounce_task.done():
                        debounce_task.cancel()
                    if len(audio_buffer) >= MIN_AUDIO_BYTES:
                        await process_whisper_utterance()
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected session=%s", session_id)
        call_active = False
    except Exception as exc:
        logger.exception("WebSocket error session=%s", session_id)
        from app.debug_log import debug_log

        debug_log(
            hypothesis_id="H-DISCONNECT",
            location="stream.py:audio_stream",
            message="websocket exception",
            data={
                "session_id": session_id,
                "error": type(exc).__name__,
                "detail": str(exc)[:300],
            },
            run_id="call",
        )
        raise
    finally:
        call_active = False
        if debounce_task and not debounce_task.done():
            debounce_task.cancel()
        if call_sid:
            call_registry.unregister(call_sid)
        session_memory.clear(session_id)
        logger.info("Call ended session=%s", session_id)
