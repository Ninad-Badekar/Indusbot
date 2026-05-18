import audioop
import io
import struct

import numpy as np
from faster_whisper import WhisperModel

from app.config import settings

_model: WhisperModel | None = None


def _ulaw_to_pcm16(ulaw_bytes: bytes) -> bytes:
    return audioop.ulaw2lin(ulaw_bytes, 2)


def _pcm16_to_float32(pcm_bytes: bytes) -> np.ndarray:
    count = len(pcm_bytes) // 2
    samples = struct.unpack(f"<{count}h", pcm_bytes)
    return np.array(samples, dtype=np.float32) / 32768.0


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr:
        return audio
    ratio = target_sr / orig_sr
    new_len = int(len(audio) * ratio)
    return np.interp(
        np.linspace(0, len(audio) - 1, new_len),
        np.arange(len(audio)),
        audio,
    )


_voice_model: WhisperModel | None = None


def get_stt_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(settings.whisper_model_size, device="cpu", compute_type="int8")
    return _model


def get_voice_stt_model() -> WhisperModel:
    global _voice_model
    if _voice_model is None:
        _voice_model = WhisperModel(
            settings.whisper_voice_model_size, device="cpu", compute_type="int8"
        )
    return _voice_model


def transcribe_audio(audio_bytes: bytes) -> str:
    model = get_stt_model()

    pcm = _ulaw_to_pcm16(audio_bytes)
    audio_float = _pcm16_to_float32(pcm)
    audio_16k = _resample(audio_float, 8000, 16000)

    segments, _ = model.transcribe(audio_16k, beam_size=1, language="en")
    return " ".join(segment.text for segment in segments)


def transcribe_voice_audio(audio_bytes: bytes) -> str:
    model = get_voice_stt_model()

    pcm = _ulaw_to_pcm16(audio_bytes)
    audio_float = _pcm16_to_float32(pcm)
    audio_16k = _resample(audio_float, 8000, 16000)

    segments, _ = model.transcribe(
        audio_16k,
        beam_size=3,
        language="en",
        vad_filter=True,
        condition_on_previous_text=False,
        initial_prompt=(
            "IndusDirect bank account setup. Done, okay, yes, ready, completed, "
            "customer ID, user ID, password, OTP, login."
        ),
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


async def transcribe(audio_bytes: bytes) -> str:
    import asyncio

    return await asyncio.to_thread(transcribe_audio, audio_bytes)
