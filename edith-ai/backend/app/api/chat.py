from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.dependencies import get_ai, get_memory, get_retrieval, rate_limited_user
from app.models.schemas import AssistantResponse, ChatRequest, ChatResponse
from app.security.authentication import AuthenticatedUser
from app.api.sse import sse
from app.services.assistant import assistant_events
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
    response: Response,
    user: AuthenticatedUser = Depends(rate_limited_user),
    ai: AIService = Depends(get_ai),
    memory: MemoryService = Depends(get_memory),
    retrieval: RetrievalService = Depends(get_retrieval),
) -> AssistantResponse:
    """Voice entry point for the phone app: a phone action (call, open app, music, ...) or an answer.

    The server only describes the action; the phone performs it with its own permissions.
    Prefer POST /api/assistant/stream (or /api/voice/ask) for the fastest first words.
    """
    parts: list[str] = []
    out: dict = {"kind": "answer", "sources": [], "mock": False}
    async for ev in assistant_events(body, user.id, ai, memory, retrieval):
        t = ev["type"]
        if t == "token":
            parts.append(ev["t"])
            out["mock"] = out["mock"] or bool(ev.get("mock"))
        elif t == "action":
            out.update(kind="action", action=ev["action"], say=ev["say"])
        elif t in ("ignore", "end"):
            out.update(kind=t, say=ev.get("say"))
        elif t == "sources":
            out["sources"] = ev["sources"]
        elif t == "meta":
            out["model"] = ev.get("model")
        elif t == "done":
            out["model"] = ev.get("model") or out.get("model")
            response.headers["Server-Timing"] = ", ".join(
                f"{k.removesuffix('_ms')};dur={v}" for k, v in ev.get("timings", {}).items())
    if out["kind"] == "answer":
        out["reply"] = "".join(parts).strip()
    return AssistantResponse(**out)


@router.post("/assistant/stream")
async def assistant_stream(
    body: ChatRequest,
    user: AuthenticatedUser = Depends(rate_limited_user),
    ai: AIService = Depends(get_ai),
    memory: MemoryService = Depends(get_memory),
    retrieval: RetrievalService = Depends(get_retrieval),
) -> StreamingResponse:
    """Server-sent events: meta (route/model, sent at once), token..., action | ignore | end, done (timings)."""
    return sse(assistant_events(body, user.id, ai, memory, retrieval))
