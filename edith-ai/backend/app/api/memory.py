from fastapi import APIRouter, Depends, status

from app.dependencies import current_user, get_memory
from app.models.schemas import Memory, MemoryCreate, MemorySettings, MemoryUpdate
from app.security.authentication import AuthenticatedUser
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=list[Memory])
def list_memories(user: AuthenticatedUser = Depends(current_user),
                  svc: MemoryService = Depends(get_memory)) -> list[Memory]:
    """Memories owned by the authenticated user only."""
    return svc.list(user.id)


@router.post("", response_model=Memory, status_code=status.HTTP_201_CREATED)
def create_memory(body: MemoryCreate, user: AuthenticatedUser = Depends(current_user),
                  svc: MemoryService = Depends(get_memory)) -> Memory:
    """Explicitly save a user-approved memory."""
    return svc.create(user.id, body)


@router.get("/settings", response_model=MemorySettings)
def get_settings(user: AuthenticatedUser = Depends(current_user),
                 svc: MemoryService = Depends(get_memory)) -> MemorySettings:
    return MemorySettings(memory_enabled=svc.is_enabled(user.id))


@router.put("/settings", response_model=MemorySettings)
def put_settings(body: MemorySettings, user: AuthenticatedUser = Depends(current_user),
                 svc: MemoryService = Depends(get_memory)) -> MemorySettings:
    """Turn persistent memory on/off. When off, memories are neither saved nor used."""
    svc.set_enabled(user.id, body.memory_enabled)
    return MemorySettings(memory_enabled=svc.is_enabled(user.id))


@router.patch("/{memory_id}", response_model=Memory)
def update_memory(memory_id: str, body: MemoryUpdate,
                  user: AuthenticatedUser = Depends(current_user),
                  svc: MemoryService = Depends(get_memory)) -> Memory:
    return svc.update(user.id, memory_id, body)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: str, user: AuthenticatedUser = Depends(current_user),
                  svc: MemoryService = Depends(get_memory)) -> None:
    """Delete a memory the user owns. Returns 404 for missing *or* foreign ids."""
    svc.delete(user.id, memory_id)
