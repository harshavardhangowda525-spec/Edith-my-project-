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
                           memories=memories, sources=sources, language=body.language,
                           address=body.address)
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
    message = body.message
    directed = True
    if body.followup:
        quick = command_service.followup_kind(message)
        if quick == "end":
            return AssistantResponse(kind="end", say="Okay.")
        if quick == "ignore":
            return AssistantResponse(kind="ignore")
        if quick == "wake":
            return AssistantResponse(kind="answer", reply="Yes?")
        directed = command_service.addressed_to_edith(message)
        if directed:
            message = command_service.strip_wake_word(message)

    action = await command_service.understand(message, ai, allow_ai=directed)
    if action:
        return AssistantResponse(kind="action", action=action, say=command_service.describe(action))
    memories = memory.for_prompt(user.id) if body.use_memory else []
    sources = retrieval.search(user.id, message) if body.use_documents else []
    prompt = message if directed else message + command_service.FOLLOWUP_NOTE
    result = await ai.chat(prompt, body.history, mode=body.mode, model=body.model,
                           memories=memories, sources=sources, language=body.language,
                           address=body.address)
    if not directed and command_service.NOT_FOR_ME in result.text.upper().replace(" ", "_"):
        return AssistantResponse(kind="ignore", model=result.model, mock=result.mock)
    return AssistantResponse(kind="answer", reply=result.text, model=result.model, mock=result.mock,
                             sources=sources)
