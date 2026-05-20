import json
import logging
import time

from fastapi import APIRouter, Request, Response

from app.config import settings
from app.services.voice_pipeline import try_process_utterance

logger = logging.getLogger(__name__)
router = APIRouter()

_CONFIDENCE_THRESHOLD = 0.9


def _extract_transcript(raw: str) -> str | None:
    """Parse Twilio TranscriptionData JSON and return transcript text if confidence is high enough."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw.strip() or None

    transcript = (data.get("transcript") or "").strip()
    if not transcript:
        return None

    confidence = data.get("confidence")
    if confidence is not None and confidence < _CONFIDENCE_THRESHOLD:
        logger.info("Low confidence transcription (%.2f): %s", confidence, transcript[:60])
        return None

    return transcript


@router.post("/transcription-callback")
async def transcription_callback(request: Request):
    if settings.stt_provider != "twilio":
        return Response(status_code=200)

    form = await request.form()
    event = form.get("TranscriptionEvent", "")

    if event == "transcription-started":
        call_sid = form.get("CallSid") or ""
        session_id = request.query_params.get("session_id") or call_sid
        if call_sid:
            from app.services.call_registry import call_registry

            call_registry.register_pending(call_sid, session_id)
        logger.info("Transcription started call_sid=%s session=%s", call_sid, session_id[:8])
        return Response(status_code=200)

    if event == "transcription-stopped":
        logger.info("Transcription stopped call_sid=%s", form.get("CallSid"))
        return Response(status_code=200)

    if event == "transcription-error":
        logger.error(
            "Transcription error call_sid=%s detail=%s",
            form.get("CallSid"),
            form.get("TranscriptionError", ""),
        )
        return Response(status_code=200)

    if event != "transcription-content":
        return Response(status_code=200)

    final = str(form.get("Final", "")).lower() == "true"
    if not final:
        return Response(status_code=200)

    raw = (form.get("TranscriptionData") or "").strip()
    if not raw:
        return Response(status_code=200)

    user_text = _extract_transcript(raw)
    if not user_text:
        return Response(status_code=200)

    call_sid = form.get("CallSid") or ""
    session_id = request.query_params.get("session_id") or call_sid

    t0 = time.monotonic()
    await try_process_utterance(
        session_id=session_id,
        user_text=user_text,
        call_sid=call_sid,
        stt_ms=0,
    )
    logger.info(
        "[%s] Transcription processed in %dms: %s",
        session_id[:8],
        int((time.monotonic() - t0) * 1000),
        user_text[:80],
    )

    return Response(status_code=200)
