from pathlib import Path

from pydantic_settings import BaseSettings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"
_DEFAULT_PIPER_VOICE = _PROJECT_ROOT / "models" / "voice.onnx"


class Settings(BaseSettings):
    app_name: str = "Ava - Corporate Banking Voice Assistant"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    ollama_voice_model: str = "llama3.2:1b"

    database_url: str = "postgresql+asyncpg://ava:ava@localhost:5432/ava"

    stt_provider: str = "twilio"
    whisper_model_size: str = "base"
    whisper_voice_model_size: str = "base"
    twilio_transcription_engine: str = "deepgram"
    twilio_transcription_speech_model: str = "nova-2"
    twilio_transcription_hints: str = (
        "Done, done, okay, yes, IndusDirect, customer ID, user ID, password, OTP, login, proceed"
    )
    twilio_transcription_language: str = "en-US"
    voice_max_history_turns: int = 2
    voice_silence_seconds: float = 1.0
    voice_utterance_cooldown_seconds: float = 4.0
    piper_voice_path: str = str(_DEFAULT_PIPER_VOICE)

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    # Public HTTPS base URL for Twilio webhooks (e.g. https://xxxx.ngrok-free.app)
    public_base_url: str = ""

    max_session_history: int = 10
    retrieval_top_k: int = 3

    class Config:
        env_file = str(_ENV_FILE) if _ENV_FILE.exists() else ".env"
        env_file_encoding = "utf-8"


settings = Settings()
