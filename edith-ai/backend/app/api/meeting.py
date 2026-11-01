"""EDITH Meeting Assistant.

Works only from user-provided documents and text the user pastes or dictates via
push-to-talk. There is no background or covert recording anywhere in EDITH.
"""
from fastapi import APIRouter, Depends

from app.dependencies import get_ai, get_retrieval, rate_limited_user
from app.errors import ValidationFailed
from app.models.schemas import MeetingBriefingRequest, MeetingResponse, MeetingSummaryRequest
from app.security.authentication import AuthenticatedUser
from app.services.ai_service import AIService
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/api/meeting", tags=["meeting"])

BRIEFING_PROMPT = """Prepare a meeting briefing on: {topic}

Using ONLY the document excerpts provided, produce:
1. Key points (bullets)
2. Technical details / architecture relevant to the topic
3. Likely questions and concise suggested answers
4. Missing or uncertain information - list anything the excerpts do not cover.
If the excerpts are empty or irrelevant, say so and do not invent content."""

SUMMARY_PROMPT = """Summarise these meeting notes. Produce: a 2-3 sentence overview, decisions, \
action items (owner if stated), open questions, and anything unclear. Do not add facts that are \
not in the notes.

NOTES:
{notes}"""


@router.post("/briefing", response_model=MeetingResponse)
async def briefing(body: MeetingBriefingRequest, user: AuthenticatedUser = Depends(rate_limited_user),
                   ai: AIService = Depends(get_ai),
                   retrieval: RetrievalService = Depends(get_retrieval)) -> MeetingResponse:
    sources = retrieval.search(user.id, body.topic, k=6, document_ids=body.document_ids or None,
                               min_score=0.1)
    result = await ai.chat(BRIEFING_PROMPT.format(topic=body.topic), [], mode="detailed",
                           sources=sources)
    return MeetingResponse(content=result.text, sources=sources, model=result.model, mock=result.mock)


@router.post("/summarize", response_model=MeetingResponse)
async def summarize(body: MeetingSummaryRequest, user: AuthenticatedUser = Depends(rate_limited_user),
                    ai: AIService = Depends(get_ai)) -> MeetingResponse:
    if not body.consent_confirmed:
        raise ValidationFailed("Confirm that every participant consented to notes or recording "
                               "before summarising.", code="consent_required")
    result = await ai.chat(SUMMARY_PROMPT.format(notes=body.notes), [], mode="detailed")
    return MeetingResponse(content=result.text, model=result.model, mock=result.mock)
