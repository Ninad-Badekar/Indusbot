import audioop
import subprocess
import tempfile
import wave
from pathlib import Path

from app.config import settings

_tts_cache: dict[str, bytes] = {}
_greeting_text: str | None = None


def cache_greeting(text: str) -> None:
    global _greeting_text
    _greeting_text = text
    synthesize_speech(text)


def get_cached_greeting() -> bytes | None:
    if _greeting_text and _greeting_text in _tts_cache:
        return _tts_cache[_greeting_text]
    return None


def synthesize_speech(text: str) -> bytes:
    if text in _tts_cache:
        return _tts_cache[text]

    voice_path = Path(settings.piper_voice_path)
    if not voice_path.exists():
        raise FileNotFoundError(f"Piper voice model not found at {voice_path}")

    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as txt_file:
        txt_file.write(text)
        txt_path = txt_file.name

    wav_path = txt_path.replace(".txt", ".wav")

    try:
        subprocess.run(
            ["piper", "--model", str(voice_path), "--output_file", wav_path],
            stdin=open(txt_path),
            check=True,
            capture_output=True,
        )

        with wave.open(wav_path, "rb") as wav:
            pcm = wav.readframes(wav.getnframes())
            rate = wav.getframerate()

        if rate != 8000:
            pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 8000, None)

        ulaw = audioop.lin2ulaw(pcm, 2)
        _tts_cache[text] = ulaw
        return ulaw

    finally:
        Path(txt_path).unlink(missing_ok=True)
        Path(wav_path).unlink(missing_ok=True)


async def synthesize(text: str) -> bytes:
    import asyncio

    return await asyncio.to_thread(synthesize_speech, text)
