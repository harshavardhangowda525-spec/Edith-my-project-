"""Endpoints the EDITH PC bridge talks to. Same owner token as the phone; no extra secret."""
from typing import Any

from fastapi import APIRouter, Depends, Response, status
import re

from pydantic import BaseModel, Field, field_validator

from app.dependencies import current_user, get_bridge
from app.security.authentication import AuthenticatedUser
from app.services.bridge import JOB_KINDS, BridgeHub

router = APIRouter(prefix="/api/bridge", tags=["bridge"])
_MAC = re.compile(r"^[0-9A-Fa-f]{2}([-:][0-9A-Fa-f]{2}){5}$")


class Heartbeat(BaseModel):
    hostname: str = Field(default="pc", max_length=100)
    projects: list[str] = Field(default_factory=list, max_length=50)
    version: str = Field(default="1", max_length=20)
    # Network adapter addresses, so the phone can send the wake-up signal without you typing them.
    macs: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("macs")
    @classmethod
    def _macs(cls, v: list[str]) -> list[str]:
        return [m.upper().replace("-", ":") for m in v if _MAC.match(m.strip())]


class JobResult(BaseModel):
    ok: bool
    output: str = Field(default="", max_length=60_000)


@router.get("/status")
def bridge_status(user: AuthenticatedUser = Depends(current_user),
                  hub: BridgeHub = Depends(get_bridge)) -> dict[str, Any]:
    return {**hub.status(user.id), "job_kinds": JOB_KINDS}


@router.post("/heartbeat")
def heartbeat(body: Heartbeat, user: AuthenticatedUser = Depends(current_user),
              hub: BridgeHub = Depends(get_bridge)) -> dict[str, Any]:
    hub.heartbeat(user.id, body.model_dump())
    return {"ok": True}


@router.get("/jobs/next")
async def next_job(response: Response, wait: float = 20.0, user: AuthenticatedUser = Depends(current_user),
                   hub: BridgeHub = Depends(get_bridge)) -> dict[str, Any] | None:
    """Long poll (up to 25 s). 204 when no job arrived."""
    job = await hub.claim(user.id, max(0.0, min(wait, 25.0)))
    if job is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return {"id": job.id, "kind": job.kind, "params": job.params}


@router.get("/jobs/{job_id}")
def job_state(job_id: str, user: AuthenticatedUser = Depends(current_user),
              hub: BridgeHub = Depends(get_bridge)) -> dict[str, Any]:
    """The bridge checks this while a long job runs, and stops when you cancelled the task."""
    return {"cancelled": hub.is_cancelled(user.id, job_id)}


@router.post("/jobs/{job_id}/result")
def job_result(job_id: str, body: JobResult, user: AuthenticatedUser = Depends(current_user),
               hub: BridgeHub = Depends(get_bridge)) -> dict[str, Any]:
    return {"accepted": hub.complete(user.id, job_id, body.ok, body.output)}
