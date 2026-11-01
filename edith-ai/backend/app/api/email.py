from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.dependencies import get_ai, rate_limited_user
from app.errors import ValidationFailed
from app.security.authentication import AuthenticatedUser
from app.services.ai_service import AIService
from app.services.email_service import EmailService, check_address

router = APIRouter(prefix="/api/email", tags=["email"])


class DraftRequest(BaseModel):
    to_name: str = Field(default="", max_length=200)
    instruction: str = Field(min_length=1, max_length=2000)


class SendRequest(BaseModel):
    to: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    # The app sets this only after the user heard the draft and said "yes".
    confirmed: bool


def _svc(request: Request) -> EmailService:
    return request.app.state.email


@router.post("/draft")
async def draft(body: DraftRequest, user: AuthenticatedUser = Depends(rate_limited_user),
                ai: AIService = Depends(get_ai), svc: EmailService = Depends(_svc)) -> dict:
    return await svc.draft(ai, body.to_name, body.instruction)


@router.post("/send")
async def send(body: SendRequest, user: AuthenticatedUser = Depends(rate_limited_user),
               svc: EmailService = Depends(_svc)) -> dict:
    if not body.confirmed:
        raise ValidationFailed("Read the email back to the user and get a 'yes' before sending.",
                               code="confirmation_required")
    check_address(body.to)
    await svc.send(body.to, body.subject, body.body)
    return {"sent": True}
