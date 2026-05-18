import uuid

from fastapi import APIRouter

from app.models.schemas import ChatRequest, ChatResponse
from app.services.llm import generate_response
from app.services.retrieval import search
from app.services.memory import session_memory

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    context = await search(request.message)
    history = session_memory.get_history(session_id)
    response_text = await generate_response(request.message, context, history)

    session_memory.add_turn(session_id, "user", request.message)
    session_memory.add_turn(session_id, "assistant", response_text)

    return ChatResponse(response=response_text, session_id=session_id)
