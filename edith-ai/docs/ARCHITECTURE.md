# EDITH AI — Architecture (V1)

## Voice pipeline

```
 Bluetooth earbuds (mic)                                   Bluetooth earbuds (speaker)
        │  OS default input                                          ▲ OS default output
        ▼                                                            │
 ┌──────────────── Browser (React + Vite) ─────────────────────────────────────────┐
 │ Push-to-talk ─► Web Speech recognition ──► text ─┐      speechSynthesis ◄──┐   │
 │   (held only)    └ fallback: MediaRecorder clip ─┼─► /api/voice/transcribe  │   │
 │ Text input ──────────────────────────────────────┤      (optional) /speak ─┤   │
 │                                                  ▼                         │   │
 │                                    POST /api/chat  (Bearer token)  ── reply┘   │
 └──────────────────────────────────────────────────┬──────────────────────────────┘
                                                    │ HTTPS
 ┌────────────────────────── FastAPI backend ───────▼──────────────────────────────┐
 │ CORS allow-list · body-size limit · auth · per-user rate limit · error mapper   │
 │                                                                                 │
 │  api/chat ──► MemoryService (approved memories) ─┐                              │
 │           └─► RetrievalService (BM25 over chunks)┼─► AIService ─► Provider      │
 │                                                  │     prompt     adapter       │
 │  api/memory, api/documents, api/meeting, api/voice                              │
 │                                                                                 │
 │  Storage: InMemoryStore (dev) | SupabaseStore (PostgREST, service-role, server) │
 └──────────────────────────────────────┬──────────────────────────────────────────┘
                                        │
             ┌──────────────────────────┼───────────────────────────────┐
             ▼                          ▼                               ▼
   OpenAI-compatible API       Anthropic Messages API          Supabase Postgres + Auth
  (/chat/completions)          (/v1/messages, own adapter)      (RLS on every table)
```

## Backend modules

| Module | Responsibility |
|---|---|
| `app/main.py` | App factory, middleware (CORS, body limit, security headers), structured errors, log redaction |
| `app/config.py` | All settings from env / `.env` (pydantic-settings) |
| `app/dependencies.py` | Service wiring via `app.state`, auth + rate-limit dependencies |
| `app/security/authentication.py` | Supabase JWT verification (HS256 secret or JWKS for RS256/ES256); dev-only local tokens |
| `app/security/rate_limit.py` | Per-user sliding-window limiter for AI/speech endpoints |
| `app/services/ai_service.py` | Persona, prompt building, provider adapters (OpenAI-compatible, Anthropic, mock) |
| `app/services/speech_service.py` | Optional server STT/TTS adapter; validates type & size |
| `app/services/memory_service.py` | Explicit, user-approved memories; on/off switch |
| `app/services/retrieval_service.py` | Chunking + BM25 ranking for source-grounded answers |
| `app/services/storage.py` | `InMemoryStore` and `SupabaseStore` behind one interface |
| `app/api/meeting.py` | Meeting briefing (from documents) and consent-gated note summaries |

## Intelligence design

* **Persona** (`PERSONA` in `ai_service.py`): professional, concise, honest about uncertainty,
  never invents facts, treats documents/memories as data rather than instructions.
* **Modes:** `earbud` (1–3 spoken sentences, no markdown), `detailed`, `meeting`
  (suggested answer + "Missing/uncertain" line).
* **Short-term context:** the client sends the last ≤12 turns; the server does not persist them.
* **Long-term memory:** only rows the user created explicitly. Disabled → not saved, not used.
* **Retrieval:** documents are chunked (~900 chars, 150 overlap) and ranked with BM25.
  Top chunks above a threshold are injected with titles; the response returns them as `sources`
  so the UI can show exactly what the answer was grounded in.
* **Model selection:** `AI_MODEL` default; users may pick only models in `AI_ALLOWED_MODELS`.
* **Multilingual:** the `language` setting drives recognition, synthesis and reply language.

### Why separate provider adapters

OpenAI-compatible servers share `/chat/completions`, but Anthropic uses a different endpoint,
auth header, system-prompt placement and response shape. Each adapter maps errors to
`provider_auth`, `provider_rate_limited`, `provider_timeout`, etc., and never forwards
upstream response bodies to the client.

### Upgrade path for retrieval

1. Enable `pgvector` in Supabase, add `embedding vector(1536)` to `document_chunks`.
2. Embed chunks at upload time; query with a `match_chunks(user_id, query_embedding, k)` RPC.
3. Keep BM25 as a hybrid signal. The `fts` column already exists for Postgres full-text search.

## Browser platform limitations (be aware)

* **Web Speech recognition**: Chrome/Edge (desktop & Android) and Safari. Not Firefox.
  In Chrome it sends audio to Google's speech service; the app tells users this in docs.
  Firefox falls back to recording a clip and calling `/api/voice/transcribe` (requires
  `SPEECH_PROVIDER` on the server).
* **No microphone selection for Web Speech**: it always uses the OS default input. Set the
  earbuds as the default input/output device. Bluetooth headsets in "hands-free" (HFP) mode
  lower playback quality while the mic is active — a Bluetooth limitation, not an app bug.
* **Secure context**: microphone access needs `https://` or `http://localhost`.
* **Speech output** uses `speechSynthesis`; voices differ per OS.

## Privacy model

* Mic only active while push-to-talk is held. No wake word, no background capture.
* Conversations are not stored server-side in V1 (`conversations`/`messages` tables exist for a
  future opt-in history feature).
* Meeting summaries require the user to confirm participant consent (`consent_confirmed`).
* AI and service-role keys exist only in `backend/.env`.
