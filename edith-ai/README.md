# EDITH AI — Intelligent Earbud Assistant (V1)

A voice-first personal intelligence assistant you talk to through ordinary Bluetooth earbuds.
Push-to-talk → speech-to-text → AI → text-to-speech → earbuds, with user-approved memory,
document-grounded answers, and a meeting assistant.

- **Backend:** Python 3.11+, FastAPI, Pydantic, httpx. OpenAI-compatible + Anthropic adapters, mock mode.
- **Frontend:** React 18 + Vite, liquid-glass UI, animated holographic orb (idle / listening / thinking / speaking).
- **Data:** Supabase Postgres + Auth with row-level security (in-memory store for local dev).

## Quick start (Windows)

One command (checks prerequisites, creates venv and `.env` files, installs, runs tests):

```powershell
cd edith-ai
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

It prints a **local access token** — paste it into EDITH → ⚙ Settings → General → Access token.

### Manual setup

Backend:

```powershell
cd edith-ai

cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # then edit LOCAL_ACCESS_TOKENS (and AI_* for real AI)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Frontend (second terminal):

```powershell
cd edith-ai\frontend
npm install
npm run dev
```

| URL | What |
|---|---|
| <http://localhost:5173> | EDITH app (use Chrome or Edge) |
| <http://localhost:8000/health> | Backend health |
| <http://localhost:8000/docs> | Interactive API docs (dev only) |

The frontend talks to the backend at `VITE_API_URL` (`frontend/.env`, default
`http://localhost:8000`); you can also change it at runtime in Settings → General.

### Connect a real AI model

Edit `backend/.env`, then restart the backend:

```env
AI_PROVIDER=openai           # or anthropic
AI_API_KEY=<your key>
AI_MODEL=gpt-4o-mini
```

Without a key EDITH runs in clearly-labeled **mock mode**. Full provider list and Supabase setup:
[`docs/API_SETUP.md`](docs/API_SETUP.md).

### Use with Bluetooth earbuds

1. Pair your earbuds and set them as the **default input and output** device
   (Windows: Settings → System → Sound; Android: just connect them).
2. Open EDITH in Chrome/Edge, click **Check** under *Mic* and allow microphone access.
3. Hold **Hold to talk** (or the **Space** bar), speak, release. EDITH answers in your earbuds.
   Press **Stop speaking** (or Esc) to interrupt.

> Browsers cannot pick a specific Bluetooth microphone for speech recognition; they use the
> OS default. While the mic is active, many earbuds switch to the lower-quality hands-free
> profile. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#browser-platform-limitations-be-aware).

## Features

| Area | What V1 does |
|---|---|
| Voice | Push-to-talk only (no background listening), live transcript, browser TTS with voice/rate choice, stop playback, Firefox fallback via server STT |
| Chat | Text fallback, short-term context, response styles (earbud / detailed / meeting), language setting, model selection (server allow-list) |
| Memory | Saved only on explicit action ("Remember" or Memory tab); view / add / edit / delete; global on/off switch |
| Documents | Upload .txt/.md/.csv/.json; BM25 retrieval; answers cite sources shown under each reply |
| Meeting | Briefings from your documents (with "missing/uncertain" section); note summaries gated on participant consent |
| Security | Server-side keys, bearer auth (Supabase JWT or dev tokens), per-user rate limit, body-size limits, strict CORS, security headers, structured errors, log redaction |

## Project layout

```text
edith-ai/
├── backend/            FastAPI app (app/), tests/, requirements.txt, Dockerfile, .env.example
├── frontend/           React + Vite app (src/components, src/services, src/styles)
├── database/           schema.sql + migrations/ for Supabase
├── docs/               ARCHITECTURE, API_SETUP, DEPLOYMENT, HARDWARE_ROADMAP
├── scripts/setup.ps1   Windows setup script
└── docker-compose.yml
```

## Tests

```powershell
cd edith-ai\backend
.\.venv\Scripts\python.exe -m pytest -v
```

Covers health, chat with a mocked provider, real adapters against a mocked network
(OpenAI-compatible & Anthropic success, 401, timeout, malformed response), missing credentials,
invalid requests, oversized bodies, authentication (missing / wrong / expired / forged JWT),
rate limiting, memory & document ownership isolation, memory on/off, consent gating.

## Deployment

Docker: `docker compose up --build` → frontend <http://localhost:8080>, backend <http://localhost:8000>.
Production (HTTPS, Supabase, CORS): [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Not yet done in V1

- Live AI, Supabase and server-speech integrations are implemented but need your credentials;
  they were tested only against mocked network responses.
- Conversation history is not persisted (tables exist for a future opt-in feature).
- PDF/DOCX upload (text formats only); vector embeddings (BM25 for now).
- Streaming responses / streaming speech; native Android companion app; custom hardware
  (see [`docs/HARDWARE_ROADMAP.md`](docs/HARDWARE_ROADMAP.md)).
