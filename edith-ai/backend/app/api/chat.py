from fastapi import APIRouter, Depends

from app.dependencies import get_ai, get_memory, get_retrieval, rate_limited_user
from app.models.schemas import AssistantResponse, ChatRequest, ChatResponse
from app.security.authentication import AuthenticatedUser
from app.services import command_service
from app.services.ai_service import AIService
from app.services.memory_service import MemoryService
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: AuthenticatedUser = Depends(rate_limited_user),
    ai: AIService = Depends(get_ai),
    memory: MemoryService = Depends(get_memory),
    retrieval: RetrievalService = Depends(get_retrieval),
) -> ChatResponse:
    """Send a message to EDITH. Conversation content is NOT stored automatically."""
    memories = memory.for_prompt(user.id) if body.use_memory else []
    sources = retrieval.search(user.id, body.message) if body.use_documents else []
    result = await ai.chat(body.message, body.history, mode=body.mode, model=body.model,
                           memories=memories, sources=sources, language=body.language)
    return ChatResponse(reply=result.text, model=result.model, provider=result.provider,
                        mock=result.mock, sources=sources, memories_used=len(memories))


@router.post("/assistant", response_model=AssistantResponse)
async def assistant(
    body: ChatRequest,
    user: AuthenticatedUser = Depends(rate_limited_user),
    ai: AIService = Depends(get_ai),
    memory: MemoryService = Depends(get_memory),
    retrieval: RetrievalService = Depends(get_retrieval),
) -> AssistantResponse:
    """Voice entry point for the phone app: a phone action (call, open app, music, ...) or an answer.

    The server only describes the action; the phone performs it with its own permissions.
    """
    action = await command_service.understand(body.message, ai)
    if action:
        return AssistantResponse(kind="action", action=action, say=command_service.describe(action))
    memories = memory.for_prompt(user.id) if body.use_memory else []
    sources = retrieval.search(user.id, body.message) if body.use_documents else []
    result = await ai.chat(body.message, body.history, mode=body.mode, model=body.model,
                           memories=memories, sources=sources, language=body.language)
    return AssistantResponse(kind="answer", reply=result.text, model=result.model, mock=result.mock,
                             sources=sources)
