import logging
import time

from fastapi import WebSocket

from app.config import settings
from app.conversation_log import log_speech
from app.debug_log import debug_log
from app.services.llm import stream_voice_sentences
from app.services.memory import session_memory
from app.services.retrieval import get_step_content, search, extract_step_responses
from app.services.voice_outbound import stream_sentences_to_caller

logger = logging.getLogger(__name__)

VOICE_RETRIEVAL_TOP_K = 1


async def _kb_sentences(responses: list[str], is_active: callable):
    """Async generator yielding KB response sentences one by one."""
    for resp in responses:
        if not is_active():
            break
        yield resp


async def run_voice_pipeline(
    *,
    session_id: str,
    user_text: str,
    websocket: WebSocket,
    stream_sid: str | None,
    is_active: callable,
    stt_ms: int = 0,
) -> None:
    if not user_text.strip():
        return

    if session_memory.is_completed(session_id):
        logger.info("[%s] Session completed, skipping utterance", session_id[:8])
        return

    log_speech(session_id, "caller", user_text)

    step = session_memory.get_step(session_id)
    if session_memory.is_confirmation(user_text):
        step = session_memory.advance_step(session_id)
        logger.info("[%s] User confirmed — advanced to step %d", session_id[:8], step)

    step_query = f"Step {step} for IndusDirect setup guide"
    context = await get_step_content(step)
    if not context:
        context = await search(step_query, top_k=VOICE_RETRIEVAL_TOP_K)
    fallback_phrases = ("Fallback", "Confused", "OTP", "Website Not Opening", "Human Support")
    if not context.strip() or any(p in context[:80] for p in fallback_phrases):
        context = await search(user_text, top_k=VOICE_RETRIEVAL_TOP_K)

    t0 = time.monotonic()
    t_retrieval = time.monotonic()
    debug_log(
        hypothesis_id="H5",
        location="voice_pipeline.py:run_voice_pipeline",
        message="RAG context for voice turn",
        data={
            "user_text": user_text[:120],
            "current_step": step,
            "step_query": step_query,
            "context_len": len(context),
            "context_empty": not bool(context.strip()),
            "context_preview": context[:200] if context else "",
        },
        run_id="voice",
    )

    history = session_memory.get_history(session_id)

    use_llm = False
    kb_responses = extract_step_responses(context) if 1 <= step <= 8 else []
    user_lower = user_text.lower()
    is_goodbye = step >= 8 and any(w in user_lower for w in ("bye", "goodbye", "thanks", "thank"))

    if kb_responses and is_goodbye:
        # Goodbye after Step 8 completion
        async def _goodbye_sentences():
            yield "You're welcome."
            yield "Your IndusDirect setup is complete."
            yield "Goodbye."
        sentences = _goodbye_sentences()
    elif kb_responses and 1 <= step <= 8:
        # Direct step instruction from KB — no LLM needed
        sentences = _kb_sentences(kb_responses, is_active)
    else:
        # LLM path for non-step / fallback content
        use_llm = True
        context_with_step = f"[Current step: {step}]\n{context}"
        sentences = stream_voice_sentences(user_text, context_with_step, history)

    session_memory.set_bot_speaking(session_id, True)
    try:
        ai_response, tts_ms, first_audio_ms = await stream_sentences_to_caller(
            websocket,
            stream_sid,
            sentences,
            is_active=is_active,
            on_sentence=lambda s: log_speech(session_id, "bot", s),
        )
    finally:
        session_memory.set_bot_speaking(session_id, False)

    t_done = time.monotonic()
    llm_ms = int((t_done - t_retrieval) * 1000) - tts_ms

    if not ai_response.strip():
        logger.warning("[%s] Bot produced empty response for caller input", session_id[:8])
        return

    if is_goodbye:
        session_memory.mark_completed(session_id)

    log_speech(
        session_id,
        "bot_full",
        ai_response,
        extra={"stt_ms": stt_ms, "llm_ms": llm_ms, "tts_ms": tts_ms},
    )

    session_memory.add_turn(session_id, "user", user_text)
    session_memory.add_turn(session_id, "assistant", ai_response)

    logger.info(
        "Voice response: stt_ms=%d retrieval_ms=%d llm_ms=%d tts_ms=%d "
        "first_audio_ms=%d total_ms=%d",
        stt_ms,
        int((t_retrieval - t0) * 1000),
        llm_ms if use_llm else 0,
        tts_ms,
        first_audio_ms,
        int((t_done - t0) * 1000),
    )


async def try_process_utterance(
    *,
    session_id: str,
    user_text: str,
    call_sid: str | None,
    stt_ms: int = 0,
) -> bool:
    """Run pipeline if guards pass. Returns True if processing started."""
    from app.services.call_registry import call_registry

    if session_memory.is_bot_speaking(session_id):
        logger.info("[%s] Skipping utterance — bot is speaking", session_id[:8])
        return False

    if session_memory.is_processing(session_id):
        logger.info("[%s] Skipping utterance — pipeline busy", session_id[:8])
        return False

    active_call = call_registry.get(call_sid) if call_sid else None
    if active_call is None:
        logger.warning("[%s] No active call for call_sid=%s", session_id[:8], call_sid)
        return False

    if active_call.websocket is None:
        logger.info("[%s] Stream not ready yet, skipping utterance", session_id[:8])
        return False

    if not active_call.is_active():
        return False

    cooldown = settings.voice_utterance_cooldown_seconds
    if time.monotonic() - active_call.last_processed_at < cooldown:
        return False

    async with active_call.pipeline_lock:
        if time.monotonic() - active_call.last_processed_at < cooldown:
            return False
        if session_memory.is_processing(session_id):
            return False

        session_memory.set_processing(session_id, True)
        try:
            active_call.last_processed_at = time.monotonic()
            await run_voice_pipeline(
                session_id=session_id,
                user_text=user_text,
                websocket=active_call.websocket,
                stream_sid=active_call.stream_sid,
                is_active=active_call.is_active,
                stt_ms=stt_ms,
            )
        except Exception as exc:
            logger.exception("Voice pipeline failed")
            debug_log(
                hypothesis_id="H4",
                location="voice_pipeline.py:try_process_utterance",
                message="pipeline exception",
                data={"error": type(exc).__name__, "detail": str(exc)[:300]},
                run_id="voice",
            )
        finally:
            session_memory.set_processing(session_id, False)

    return True
