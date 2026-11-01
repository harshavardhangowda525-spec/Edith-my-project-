"""EDITH Meeting Assistant.

Briefings and summaries work from user-provided documents and notes. Live help (/assist)
receives short transcript lines from the phone app's Meeting mode, which the user switches on
explicitly after confirming participants know an AI assistant is listening. The app shows a
notification the whole time; no audio or transcript is stored on the server.
"""
from fastapi import APIRouter, Depends

from app.dependencies import get_ai, get_memory, get_retrieval, rate_limited_user
from app.errors import ValidationFailed
from app.models.schemas import (
    MeetingAssistRequest,
    MeetingAssistResponse,
    MeetingBriefingRequest,
    MeetingResponse,
    MeetingSummaryRequest,
)
from app.security.authentication import AuthenticatedUser
from app.services.ai_service import AIService
from app.services.memory_service import MemoryService
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


ASSIST_PROMPT = """You are whispering to the user through an earbud during a live meeting. Below is
the recent transcript of what was said in the room (speakers are not labelled; the newest line is last).

{transcript}

{instruction}

Answer rules: at most 2 short sentences of plain speech the user can repeat to the client, no
markdown. If you are not sure, say so briefly instead of guessing. Use the document excerpts and
memories when relevant. Never invent project facts, prices, dates or commitments.
Start your reply with the question in one line as "Q: <question>", then the answer on the next line."""

AUTO_INSTRUCTION = """Decide whether the NEWEST line (or the last two lines together) is a question
someone asked that the user may need help answering: a factual, technical, business or project
question. If it is small talk, a greeting, an instruction, rhetorical, already answered in the
transcript, or not a question, reply with exactly NO_ANSWER and nothing else."""

FORCE_INSTRUCTION = """The user pressed the help button: answer the most recent question in the
transcript. If there is no question at all, briefly summarise the last point in one sentence."""


@router.post("/assist", response_model=MeetingAssistResponse)
async def assist(body: MeetingAssistRequest, user: AuthenticatedUser = Depends(rate_limited_user),
                 ai: AIService = Depends(get_ai), memory: MemoryService = Depends(get_memory),
                 retrieval: RetrievalService = Depends(get_retrieval)) -> MeetingAssistResponse:
    """Live meeting help: answer the client's latest question (consent required, nothing stored)."""
    if not body.consent_confirmed:
        raise ValidationFailed("Confirm that meeting participants know an AI assistant is listening.",
                               code="consent_required")
    recent = body.transcript[-12:]
    query = " ".join(recent[-2:])
    sources = retrieval.search(user.id, query, k=3, min_score=0.15)
    memories = memory.for_prompt(user.id)
    prompt = ASSIST_PROMPT.format(transcript="\n".join(f"- {line}" for line in recent),
                                  instruction=FORCE_INSTRUCTION if body.force else AUTO_INSTRUCTION)
    result = await ai.chat(prompt, [], mode="earbud", memories=memories, sources=sources,
                           language=body.language)
    text = result.text.strip()
    if not text or (not body.force and "NO_ANSWER" in text.upper().replace(" ", "_")):
        return MeetingAssistResponse(answer=None, model=result.model, mock=result.mock)
    question = None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith("q:"):
        question = lines[0][2:].strip() or None
        lines = lines[1:]
    answer = " ".join(lines).strip() or text
    return MeetingAssistResponse(answer=answer, question=question, sources=sources,
                                 model=result.model, mock=result.mock)
