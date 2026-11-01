import csv
import io

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.dependencies import current_user, rate_limited_user
from app.errors import NotFoundError
from app.security.authentication import AuthenticatedUser
from app.services.leads_service import LeadsService

router = APIRouter(prefix="/api/leads", tags=["leads"])


class LeadSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200, description="e.g. 'dentists in Indiranagar Bangalore'")
    max_leads: int = Field(default=20, ge=1, le=60)
    language: str | None = Field(default=None, max_length=20)


class LeadIn(BaseModel):
    place_id: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=300)
    phone: str | None = Field(default=None, max_length=50)
    phone_international: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=500)
    rating: float | None = None
    reviews: int | None = None
    maps_url: str | None = Field(default=None, max_length=1000)
    social_url: str | None = Field(default=None, max_length=1000)
    query: str | None = Field(default=None, max_length=200)
    status: str = Field(default="new", pattern="^(new|called|interested|not_interested|won)$")
    notes: str | None = Field(default=None, max_length=2000)


def _service(request: Request) -> LeadsService:
    return request.app.state.leads


@router.post("/search")
async def search(body: LeadSearchRequest, user: AuthenticatedUser = Depends(rate_limited_user),
                 svc: LeadsService = Depends(_service)) -> dict:
    """Businesses matching the query that have NO website (or only a social-media page)."""
    return await svc.search(body.query, body.max_leads, language=body.language)


@router.get("")
def list_leads(request: Request, user: AuthenticatedUser = Depends(current_user)) -> list[dict]:
    return request.app.state.store.list_leads(user.id)


@router.post("", status_code=status.HTTP_201_CREATED)
def save_lead(body: LeadIn, request: Request, user: AuthenticatedUser = Depends(current_user)) -> dict:
    return request.app.state.store.save_lead(user.id, body.model_dump())


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(lead_id: str, request: Request, user: AuthenticatedUser = Depends(current_user)) -> None:
    if not request.app.state.store.delete_lead(user.id, lead_id):
        raise NotFoundError("Lead not found")


@router.get("/export.csv")
def export_csv(request: Request, user: AuthenticatedUser = Depends(current_user)) -> Response:
    rows = request.app.state.store.list_leads(user.id)
    out = io.StringIO()
    cols = ["name", "phone", "phone_international", "address", "rating", "reviews", "status", "notes",
            "social_url", "maps_url", "query", "created_at"]
    w = csv.writer(out)
    w.writerow(cols)
    for r in rows:
        # Neutralise spreadsheet formulas in text cells (CSV injection).
        w.writerow([("'" + str(v)) if isinstance(v, str) and v[:1] in "=+-@" else ("" if v is None else v)
                    for v in (r.get(c) for c in cols)])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="edith-leads.csv"'})
