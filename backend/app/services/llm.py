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


async def warmup() -> None:
    async with httpx.AsyncClient(timeout=300.0) as client:
        await _warm_model(client, settings.ollama_model)
        await _warm_model(client, settings.ollama_voice_model)


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
