"""Human-readable conversation logging for voice calls."""

import logging

from app.debug_log import debug_log

logger = logging.getLogger("conversation")


def log_speech(
    session_id: str,
    speaker: str,
    text: str,
    *,
    extra: dict | None = None,
) -> None:
    """Log what was said on a call (caller or bot). Visible in server logs and debug NDJSON."""
    text = (text or "").strip()
    if not text:
        return

    sid = session_id[:8] if session_id else "unknown"
    logger.info("[%s] %s: %s", sid, speaker.upper(), text)

    payload = {
        "session_id": session_id,
        "speaker": speaker,
        "text": text,
    }
    if extra:
        payload.update(extra)

    # region agent log
    debug_log(
        hypothesis_id="CONV",
        location="conversation_log.py:log_speech",
        message=f"{speaker} spoke",
        data=payload,
        run_id="conversation",
    )
    # endregion
