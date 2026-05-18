import asyncio
import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.database import init_db
from app.services.retrieval import load_knowledge_base
from app.services.tts import cache_greeting
from app.services.llm import warmup
from app.routers import calls, stream, chat, transcription


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.debug_log import debug_log
    from app.services import retrieval
    from app.services.llm import SYSTEM_PROMPT, OFF_TOPIC_FALLBACK

    await init_db()
    load_knowledge_base()
    greeting = (
        "Hello. I will help you setup your IndusDirect account step by step. "
        "After each step, please say Done when you are finished. "
        "Step 1: Please click on the link in your welcome email "
        "or visit the official IndusDirect website. "
        "When you are done, please say Done."
    )
    asyncio.create_task(asyncio.to_thread(cache_greeting, greeting))
    # region agent log
    debug_log(
        hypothesis_id="H3-H4",
        location="main.py:lifespan",
        message="App startup",
        data={
            "app_name": settings.app_name,
            "kb_chunks": len(retrieval._chunks),
            "kb_index_ready": retrieval._index is not None,
            "system_prompt_has_indusdirect": "IndusDirect" in SYSTEM_PROMPT,
            "system_prompt_has_corporate_opening": "opening a corporate bank account"
            in SYSTEM_PROMPT.lower(),
            "off_topic_fallback": OFF_TOPIC_FALLBACK,
        },
    )
    # endregion
    # Warmup in background so Twilio webhook is not blocked (~15s model load).
    asyncio.create_task(warmup())
    yield


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("conversation").setLevel(logging.INFO)

app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(calls.router, tags=["calls"])
app.include_router(transcription.router, tags=["transcription"])
app.include_router(stream.router, tags=["stream"])
app.include_router(chat.router, prefix="/api", tags=["chat"])


@app.get("/health")
async def health():
    return {"status": "ok"}
