import json
import re

import httpx

from app.config import settings

SYSTEM_PROMPT = """You are Ava, an IndusDirect setup assistant.

Your role:
Help users complete first-time IndusDirect setup and login, step by step.

Rules:
- Answer only using the knowledge base context provided.
- Give only ONE step at a time.
- Advance to the next step only after the user confirms (Done, ok, I did it, yes, completed, finished, or similar).
- If the user has not confirmed, repeat the current step or ask them to say Done when ready.
- Never mention seconds, timers, pauses, or that you are waiting for the user.
- Never ask for company name, business location, registration documents, or corporate account details.
- Never help with corporate bank account opening or topics outside IndusDirect setup.
- Never ask users to say passwords or OTPs aloud.
- Never invent steps or legal or financial information.
- Keep responses short and conversational for voice calls.

If the user asks about anything other than IndusDirect setup, politely say you can only help with IndusDirect setup.

Tone: Professional, friendly, calm."""

OFF_TOPIC_FALLBACK = "I can only help with IndusDirect setup. What step are you on?"

VOICE_SUFFIX = (
    "\n\nRead the <context> and output ONLY the step instruction as a "
    "single natural spoken sentence. Do not add greetings, transitions, "
    "confirmations, or any other words. Do not refer to previous steps "
    "or the caller's statements. No labels, lists, or markdown."
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_ROLE_LINE = re.compile(
    r"^\s*(user|assistant|caller|ava)\s*:\s*(.*)$",
    re.IGNORECASE,
)


def _sanitize_voice_output(text: str, user_message: str) -> str:
    """Strip chat-template artifacts (e.g. 'user: yes i am ready') from voice LLM output."""
    if not text:
        return ""

    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        role_match = _ROLE_LINE.match(stripped)
        if role_match:
            role, content = role_match.group(1).lower(), role_match.group(2).strip()
            if role in ("assistant", "ava") and content:
                lines.append(content)
            continue
        lines.append(stripped)

    cleaned = " ".join(lines)

    um = user_message.strip().lower()
    cl = cleaned.lower()
    if um and cl.startswith(um):
        cleaned = cleaned[len(user_message) :].lstrip(" .,:-")

    return cleaned.strip()


def _build_prompt(
    user_message: str,
    context: str,
    history: list[dict],
    *,
    max_turns: int | None = None,
) -> str:
    parts = [SYSTEM_PROMPT, ""]

    if context:
        parts.append(f"<context>\n{context}\n</context>")
        parts.append("")

    if history:
        limit = (max_turns or settings.max_session_history) * 2
        parts.append("Previous conversation:")
        for turn in history[-limit:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            label = "Ava" if role == "assistant" else "Caller"
            parts.append(f"{label}: {content}")
        parts.append("")

    parts.append(f"Caller: {user_message}")
    parts.append("Ava:")

    return "\n".join(parts)


def _extract_sentences(buffer: str) -> tuple[list[str], str]:
    """Split completed sentences from buffer; return (sentences, remainder)."""
    sentences: list[str] = []
    parts = _SENTENCE_END.split(buffer)
    if len(parts) > 1:
        for part in parts[:-1]:
            part = part.strip()
            if part:
                sentences.append(part)
        return sentences, parts[-1]
    return sentences, buffer


async def _warm_model(client: httpx.AsyncClient, model: str) -> None:
    try:
        payload = {"model": model, "prompt": "Hello", "stream": False}
        await client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
    except Exception:
        pass


_INTENT_CACHE: dict[str, str] = {}

# Fast-path sets: zero-latency keyword matching before any LLM call
_CONFIRM_WORDS = frozenset({
    "done", "yes", "i did", "i did it", "i'm done", "im done",
    "completed", "finished", "good to go", "proceed", "i am done",
    "yup", "yep", "sure", "all done", "all set",
})

_REPEAT_WORDS = frozenset({
    "can you repeat", "repeat", "say again", "what",
    "i don't understand", "i don't get it", "help", "confused",
    "what do i do", "what should i do", "how do i do this",
    "not yet", "still working", "wait", "hold on",
})


def _classify_fallback(user_text: str) -> str:
    """Regex-based fallback when LLM output is unusable."""
    from app.services.memory import _CONFIRMATION, _NEGATED_CONFIRMATION

    text_lower = user_text.lower().strip().rstrip(".!? ")

    # Check negation first — if stripped text has no confirmation, skip
    stripped = _NEGATED_CONFIRMATION.sub("", text_lower).strip()
    if _CONFIRMATION.search(stripped):
        return "confirm"

    # Implicit confirmation: user is moving on without saying "Done"
    implicit_confirm = r"\b(?:moving on|next step|next one|let'?s go|go ahead|onward|c ontinue)\b"
    if re.search(implicit_confirm, text_lower):
        return "confirm"

    # Repeat indicators (user wants instruction again)
    repeat_pats = (
        r"\b(?:"
        r"repeat|say again|again please|can you (?:repeat|say that again)|"
        r"i (?:do not|don't|didn't) (?:get|understand|hear)|"
        r"what was that|what did you say|come again|one more time|"
        r"not yet|not done|haven'?t done|still working|"
        r"not finished|need more time|"
        r"wait|hold on|hang on|give me a moment|"
        r"i am (?:still|not done)|i'm still)\b"
    )
    if re.search(repeat_pats, text_lower):
        return "repeat"

    # Off-topic indicators (check BEFORE confused to avoid false matches)
    off_topic_pats = (
        r"\b(?:weather|joke|story|news|sports|politics|movie|song|"
        r"recipe|cook|game|play|music|what'?s up|how'?re? you|"
        r"who are you|what can you do|tell me about|"
        r"where are you from|do you like)\b"
    )
    if re.search(off_topic_pats, text_lower):
        return "off_topic"

    # Confused indicators
    confused_pats = (
        r"\b(?:confus|help|how do i|what do i|i don'?t know|"
        r"i am (?:lost|stuck|unsure)|i'm (?:lost|stuck|confused)|"
        r"can you (?:help|explain)|show me|guide me|"
        r"(?:where|what|how) (?:is|are|do|can) (?:this|that|it|now|the|i))\b"
    )
    if re.search(confused_pats, text_lower):
        return "confused"

    return "other"


async def classify_intent(
    user_text: str,
    step: int,
    step_content: str,
) -> str:
    """Classify user intent using short-prompt LLM + robust post-processing.

    Returns one of: confirm, repeat, confused, off_topic, other

    Pipeline:
      1. Fast-path sets (instant, zero LLM latency for obvious cases)
      2. Cache check (instant for repeated utterances)
      3. Short-prompt 8B LLM (2-3s on CPU for ambiguous cases)
      4. Post-process output via keyword matching
      5. Regex fallback if LLM output is unrecognisable
    """
    text_lower = user_text.lower().strip().rstrip(".!? ")

    # ---- Step 1: Fast-path sets (instant) ----
    if text_lower in _CONFIRM_WORDS:
        return "confirm"
    if text_lower in _REPEAT_WORDS:
        return "repeat"

    # ---- Step 2: Cache check ----
    cache_key = f"{step}||{user_text[:100]}"
    cached = _INTENT_CACHE.get(cache_key)
    if cached:
        return cached

    # ---- Step 3: Short-prompt 8B LLM ----
    instruction = extract_step_instruction(step_content)
    prompt = (
        f"Step {step}: {instruction[:80]}\n"
        f"User: {user_text}\n"
        f"Intent (confirm/repeat/confused/other):"
    )

    raw = ""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": settings.ollama_voice_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 5, "stop": ["\n"]},
                },
            )
            raw = resp.json().get("response", "").strip().lower().rstrip(".:! ")
    except Exception:
        pass  # Timeout or network error — fall through to regex fallback

    # ---- Step 4: Post-process LLM output ----
    if raw:
        # Check for exact match
        if raw in ("confirm", "repeat", "confused", "off_topic", "other"):
            _INTENT_CACHE[cache_key] = raw
            return raw

        # Keyword match in messy output
        if "confirm" in raw:
            result = "confirm"
        elif "repeat" in raw:
            result = "repeat"
        elif "confus" in raw:
            result = "confused"
        elif "off_topic" in raw or "off topic" in raw:
            result = "off_topic"
        elif "other" in raw:
            result = "other"
        else:
            result = _classify_fallback(user_text)
    else:
        # ---- Step 5: Regex fallback (LLM unavailable / timed out) ----
        result = _classify_fallback(user_text)

    _INTENT_CACHE[cache_key] = result
    return result


def extract_step_instruction(step_content: str) -> str:
    """Extract just the step instruction text from a KB chunk."""
    from app.services.retrieval import extract_step_responses
    responses = extract_step_responses(step_content)
    if responses:
        return " ".join(responses)
    # Fallback: first non-empty, non-heading line
    for line in step_content.split("\n"):
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("---"):
            return s[:120]
    return step_content[:120]


async def warmup() -> None:
    async with httpx.AsyncClient(timeout=300.0) as client:
        await _warm_model(client, settings.ollama_model)
        await _warm_model(client, settings.ollama_voice_model)

    # Pre-cache all KB step responses and goodbye sentences for instant TTS
    from app.services.tts import synthesize_speech
    from app.services.retrieval import get_step_content_sync, extract_step_responses

    # Collect all unique texts to cache
    texts_to_cache = []

    for step_num in range(1, 9):
        chunk = get_step_content_sync(step_num)
        if chunk:
            texts_to_cache.extend(extract_step_responses(chunk))

    texts_to_cache.extend([
        "You're welcome.",
        "Your IndusDirect setup is complete.",
        "Goodbye.",
    ])

    import asyncio
    for text in texts_to_cache:
        await asyncio.to_thread(synthesize_speech, text)


async def generate_response(
    user_message: str,
    context: str = "",
    history: list[dict] | None = None,
    *,
    voice: bool = False,
) -> str:
    if history is None:
        history = []

    if not context:
        return OFF_TOPIC_FALLBACK

    if voice:
        full = []
        async for sentence in stream_voice_sentences(user_message, context, history):
            full.append(sentence)
        return " ".join(full) if full else ""

    prompt = _build_prompt(user_message, context, history)
    options: dict = {"temperature": 0.7, "top_p": 0.9}

    async with httpx.AsyncClient(timeout=300.0) as client:
        payload = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        resp = await client.post(f"{settings.ollama_base_url}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "").strip()


async def stream_voice_sentences(
    user_message: str,
    context: str = "",
    history: list[dict] | None = None,
):
    """Yield complete sentences as they are generated by the voice LLM."""
    if history is None:
        history = []

    if not context:
        yield OFF_TOPIC_FALLBACK
        return

    if len(context) > 600:
        context = context[:600]

    history = history[-(settings.voice_max_history_turns * 2) :]
    prompt = _build_prompt(
        user_message,
        context,
        history,
        max_turns=settings.voice_max_history_turns,
    )
    prompt += VOICE_SUFFIX

    options = {
        "temperature": 0.7,
        "top_p": 0.9,
        "num_predict": 24,
        "num_ctx": 4096,
        "stop": ["\nCaller:", "\nUser:", "\nuser:", "\nassistant:"],
    }

    buffer = ""
    full_raw = ""
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.ollama_voice_model,
                "prompt": prompt,
                "stream": True,
                "options": options,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    buffer += token
                    full_raw += token
                    sentences, buffer = _extract_sentences(buffer)
                    for sentence in sentences:
                        clean = _sanitize_voice_output(sentence, user_message)
                        if clean:
                            yield clean
                if data.get("done"):
                    break

    remainder = _sanitize_voice_output(buffer.strip(), user_message)
    if remainder:
        yield remainder
    elif not full_raw.strip():
        yield "Please say Done when you have finished the current step."

    # region agent log
    from app.debug_log import debug_log

    debug_log(
        hypothesis_id="H1-H2-H4",
        location="llm.py:stream_voice_sentences",
        message="Voice LLM output complete",
        data={
            "user_message": user_message[:120],
            "prompt_tail": prompt[-450:],
            "history_turns": len(history),
            "full_llm_response": full_raw.strip()[:500],
            "contains_user_prefix": "user:" in full_raw.lower(),
            "echoes_input": user_message.lower()[:40] in full_raw.lower(),
            "sanitized_preview": _sanitize_voice_output(full_raw, user_message)[:200],
        },
        run_id="voice",
    )
    # endregion
