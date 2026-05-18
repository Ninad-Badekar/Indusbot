import asyncio
import base64
import logging
import time
from collections.abc import AsyncIterator, Callable, Awaitable

from fastapi import WebSocket

from app.services.tts import synthesize_speech

logger = logging.getLogger(__name__)

TWILIO_FRAME_BYTES = 160


async def send_ulaw_audio(
    websocket: WebSocket,
    stream_sid: str,
    ulaw: bytes,
    *,
    send_mark: bool = True,
) -> None:
    for offset in range(0, len(ulaw), TWILIO_FRAME_BYTES):
        chunk = ulaw[offset : offset + TWILIO_FRAME_BYTES]
        payload = base64.b64encode(chunk).decode()
        await websocket.send_json({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": payload},
        })
    if send_mark:
        await websocket.send_json({
            "event": "mark",
            "streamSid": stream_sid,
            "mark": {"name": f"audio-{int(time.time() * 1000)}"},
        })


async def stream_sentences_to_caller(
    websocket: WebSocket,
    stream_sid: str | None,
    sentences: AsyncIterator[str],
    *,
    is_active: Callable[[], bool],
    on_sentence: Callable[[str], Awaitable[None] | None] | None = None,
) -> tuple[str, int, int]:
    """Play TTS sentence-by-sentence. Returns (full_text, tts_ms, first_audio_ms)."""
    if not stream_sid:
        return "", 0, 0

    full_parts: list[str] = []
    tts_start = time.monotonic()
    first_audio_ms = 0
    t0 = time.monotonic()

    async for sentence in sentences:
        if not is_active():
            break
        sentence = sentence.strip()
        if not sentence:
            continue

        full_parts.append(sentence)
        if on_sentence:
            result = on_sentence(sentence)
            if asyncio.iscoroutine(result):
                await result
        ulaw = await asyncio.to_thread(synthesize_speech, sentence)
        if not is_active():
            break

        if first_audio_ms == 0:
            first_audio_ms = int((time.monotonic() - t0) * 1000)

        await send_ulaw_audio(websocket, stream_sid, ulaw)

    tts_ms = int((time.monotonic() - tts_start) * 1000)
    return " ".join(full_parts), tts_ms, first_audio_ms
