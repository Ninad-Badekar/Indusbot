import logging
import time

from fastapi import APIRouter, Request, Response

from app.config import settings
from app.services.voice_pipeline import try_process_utterance

logger = logging.getLogger(__name__)
router = APIRouter()


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

    user_text = (form.get("TranscriptionData") or "").strip()
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
