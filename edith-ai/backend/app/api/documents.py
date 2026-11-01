from fastapi import APIRouter, Depends, status

from app.dependencies import current_user, get_retrieval
from app.models.schemas import Document, DocumentCreate, Source
from app.security.authentication import AuthenticatedUser
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("", response_model=list[Document])
def list_documents(user: AuthenticatedUser = Depends(current_user),
                   svc: RetrievalService = Depends(get_retrieval)) -> list[Document]:
    return svc.list_documents(user.id)


@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
def upload_document(body: DocumentCreate, user: AuthenticatedUser = Depends(current_user),
                    svc: RetrievalService = Depends(get_retrieval)) -> Document:
    """Upload a plain-text/markdown document for retrieval (the frontend reads files client-side)."""
    return svc.add_document(user.id, body.title, body.content)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, user: AuthenticatedUser = Depends(current_user),
                    svc: RetrievalService = Depends(get_retrieval)) -> None:
    svc.delete_document(user.id, document_id)


@router.get("/search", response_model=list[Source])
def search(q: str, user: AuthenticatedUser = Depends(current_user),
           svc: RetrievalService = Depends(get_retrieval)) -> list[Source]:
    return svc.search(user.id, q[:500])
