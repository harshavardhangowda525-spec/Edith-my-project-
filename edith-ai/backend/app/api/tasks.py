from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.dependencies import current_user, get_tasks, rate_limited_user
from app.security.authentication import AuthenticatedUser
from app.services.task_handlers import TASK_TYPES
from app.services.tasks import TaskEngine

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    type: str = Field(max_length=40)
    params: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=200)
    priority: int = Field(default=5, ge=1, le=9)


@router.get("/types")
def task_types(user: AuthenticatedUser = Depends(current_user)) -> dict[str, str]:
    return TASK_TYPES


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_task(body: TaskCreate, user: AuthenticatedUser = Depends(rate_limited_user),
                      engine: TaskEngine = Depends(get_tasks)) -> dict[str, Any]:
    """Queue background work. Returns at once (202); poll GET /api/tasks/{id} for progress."""
    task = await engine.submit(user.id, body.type, body.params, body.title, body.priority)
    return task.public()


@router.get("")
def list_tasks(limit: int = 50, user: AuthenticatedUser = Depends(current_user),
               engine: TaskEngine = Depends(get_tasks)) -> list[dict[str, Any]]:
    return [t.public() for t in engine.list(user.id, max(1, min(limit, 200)))]


@router.get("/{task_id}")
def get_task(task_id: str, user: AuthenticatedUser = Depends(current_user),
             engine: TaskEngine = Depends(get_tasks)) -> dict[str, Any]:
    return engine.get(user.id, task_id).public()


@router.post("/{task_id}/cancel")
def cancel(task_id: str, user: AuthenticatedUser = Depends(current_user),
           engine: TaskEngine = Depends(get_tasks)) -> dict[str, Any]:
    return engine.cancel(user.id, task_id).public()


@router.post("/{task_id}/pause")
def pause(task_id: str, user: AuthenticatedUser = Depends(current_user),
          engine: TaskEngine = Depends(get_tasks)) -> dict[str, Any]:
    return engine.pause(user.id, task_id).public()


@router.post("/{task_id}/resume")
def resume(task_id: str, user: AuthenticatedUser = Depends(current_user),
           engine: TaskEngine = Depends(get_tasks)) -> dict[str, Any]:
    return engine.resume(user.id, task_id).public()


@router.post("/{task_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry(task_id: str, user: AuthenticatedUser = Depends(rate_limited_user),
                engine: TaskEngine = Depends(get_tasks)) -> dict[str, Any]:
    return (await engine.retry(user.id, task_id)).public()
