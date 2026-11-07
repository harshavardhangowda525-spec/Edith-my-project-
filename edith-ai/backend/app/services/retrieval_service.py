"""Document retrieval for source-grounded answers.

V1 uses a dependency-free lexical ranker (BM25) over chunked documents. It is
deterministic, private (nothing leaves the server) and good enough for a
personal knowledge base. ``docs/ARCHITECTURE.md`` describes the upgrade path to
pgvector embeddings.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from app.errors import NotFoundError
from app.models.schemas import Document, Source
from app.services.cache import TTLCache
from app.services.storage import ChunkRecord, Store

CHUNK_CHARS = 900
CHUNK_OVERLAP = 150
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by for from has have how i in is it its of on or that the this to was "
    "what when where which who why will with you your me my we our can do does".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer to break on a paragraph, then a sentence, then a space.
            window = text[start:end]
            for sep in ("\n\n", ". ", "\n", " "):
                idx = window.rfind(sep)
                if idx > size // 2:
                    end = start + idx + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


class RetrievalService:
    def __init__(self, store: Store) -> None:
        self.store = store
        # Chunks are loaded per question; cache them briefly and drop on upload/delete.
        self._chunks = TTLCache(ttl_s=60, max_items=500)

    def _user_chunks(self, user_id: str, document_ids: list[str] | None) -> list[ChunkRecord]:
        if document_ids:
            return self.store.list_chunks(user_id, document_ids)
        return self._chunks.get_or_set(user_id, lambda: self.store.list_chunks(user_id, None))

    def add_document(self, user_id: str, title: str, content: str) -> Document:
        chunks = chunk_text(content)
        d = self.store.create_document(user_id, title.strip(), chunks)
        self._chunks.invalidate(lambda k: k == user_id)
        return Document(id=d.id, user_id=d.user_id, title=d.title, chunk_count=d.chunk_count,
                        created_at=d.created_at)

    def list_documents(self, user_id: str) -> list[Document]:
        return [Document(id=d.id, user_id=d.user_id, title=d.title, chunk_count=d.chunk_count,
                         created_at=d.created_at) for d in self.store.list_documents(user_id)]

    def delete_document(self, user_id: str, document_id: str) -> None:
        if not self.store.delete_document(user_id, document_id):
            raise NotFoundError("Document not found")
        self._chunks.invalidate(lambda k: k == user_id)

    def search(self, user_id: str, query: str, k: int = 4,
               document_ids: list[str] | None = None, min_score: float = 0.5) -> list[Source]:
        chunks = self._user_chunks(user_id, document_ids)
        q_terms = tokenize(query)
        if not chunks or not q_terms:
            return []
        return [s for s in self._bm25(chunks, q_terms)[:k] if s.score >= min_score]

    @staticmethod
    def _bm25(chunks: list[ChunkRecord], q_terms: list[str], k1: float = 1.5, b: float = 0.75) -> list[Source]:
        docs = [Counter(tokenize(c.content)) for c in chunks]
        n = len(docs)
        avg_len = sum(sum(d.values()) for d in docs) / n or 1.0
        df = Counter(t for d in docs for t in set(d))
        results: list[Source] = []
        for chunk, tf in zip(chunks, docs):
            length = sum(tf.values()) or 1
            score = 0.0
            for t in set(q_terms):
                if t not in tf:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * length / avg_len))
            if score > 0:
                excerpt = chunk.content if len(chunk.content) <= 600 else chunk.content[:600] + "…"
                results.append(Source(document_id=chunk.document_id, title=chunk.title or "Untitled",
                                      chunk_index=chunk.chunk_index, excerpt=excerpt,
                                      score=round(score, 3)))
        results.sort(key=lambda s: s.score, reverse=True)
        return results
