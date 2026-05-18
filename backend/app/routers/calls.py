import logging
import uuid

from fastapi import APIRouter, Request, Response
from twilio.twiml.voice_response import VoiceResponse, Start, Connect, Stream

from app.config import settings
from app.conversation_log import log_speech
from app.debug_log import debug_log

logger = logging.getLogger(__name__)
router = APIRouter()


def _public_http_base(request: Request) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")

    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto", "https")
    if forwarded_host:
        host = forwarded_host.split(",")[0].strip()
        proto = forwarded_proto.split(",")[0].strip().lower()
        return f"{'https' if proto == 'https' else 'http'}://{host}"

    host = request.url.hostname or "localhost"
    port = request.url.port
    if port and port not in (80, 443):
        return f"http://{host}:{port}"
    return f"http://{host}"


def _build_stream_ws_url(request: Request, session_id: str) -> str:
    """Build a Twilio-reachable WebSocket URL (must be public wss, not localhost)."""
    base = _public_http_base(request)
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    return f"{ws_base}/stream?session_id={session_id}"


def _build_transcription_callback_url(request: Request, session_id: str) -> str:
    base = _public_http_base(request)
    return f"{base}/transcription-callback?session_id={session_id}"


@router.post("/incoming-call", response_class=Response)
async def incoming_call(request: Request):
    session_id = str(uuid.uuid4())
    try:
        ws_url = _build_stream_ws_url(request, session_id)
        debug_log(
            hypothesis_id="H2",
            location="calls.py:incoming_call",
            message="TwiML stream URL built",
            data={
                "ws_url": ws_url,
                "host": request.url.hostname,
                "port": request.url.port,
                "forwarded_host": request.headers.get("x-forwarded-host"),
                "forwarded_proto": request.headers.get("x-forwarded-proto"),
                "public_base_url_set": bool(settings.public_base_url),
                "stt_provider": settings.stt_provider,
            },
            run_id="call",
        )

        greeting = (
            "Hello. I will help you setup your IndusDirect account step by step. "
            "After each step, please say Done when you are finished. "
            "Step 1: Please click on the link in your welcome email "
            "or visit the official IndusDirect website. "
            "When you are done, please say Done."
        )
        log_speech(session_id, "bot_greeting", greeting)

        response = VoiceResponse()

        if settings.stt_provider == "twilio":
            start = Start()
            start.transcription(
                status_callback_url=_build_transcription_callback_url(request, session_id),
                track="inbound_track",
                transcription_engine=settings.twilio_transcription_engine,
                speech_model=settings.twilio_transcription_speech_model,
                partial_results=False,
                hints=settings.twilio_transcription_hints,
                language_code=settings.twilio_transcription_language,
            )
            response.append(start)

        connect = Connect()
        stream = Stream(url=ws_url)
        stream.parameter(name="session_id", value=session_id)
        stream.parameter(name="greeting", value=greeting)
        connect.append(stream)
        response.append(connect)

        return Response(content=str(response), media_type="text/xml")
    except Exception as exc:
        logger.exception("incoming-call failed")
        debug_log(
            hypothesis_id="H3",
            location="calls.py:incoming_call",
            message="incoming-call exception",
            data={"error": type(exc).__name__, "detail": str(exc)[:200]},
            run_id="call",
        )
        raise
