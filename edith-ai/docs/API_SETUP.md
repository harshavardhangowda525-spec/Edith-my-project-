# API & Service Setup

All secrets go in `backend/.env` (copy from `backend/.env.example`). Restart the backend after
editing. Check what's active at `GET http://localhost:8000/health` — it reports *whether* a
provider is configured, never the key.

## 1. AI provider

### OpenAI (or any OpenAI-compatible API)

```env
AI_PROVIDER=openai
AI_API_KEY=<your key>
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
AI_ALLOWED_MODELS=gpt-4o-mini,gpt-4o
```

Other compatible services — only change `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`:

| Service | `AI_BASE_URL` |
|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| Together | `https://api.together.xyz/v1` |
| Ollama (local) | `http://localhost:11434/v1` (key: any placeholder) |
| LM Studio (local) | `http://localhost:1234/v1` |

### Anthropic (Claude) — dedicated adapter

```env
AI_PROVIDER=anthropic
AI_API_KEY=<your Anthropic key>
AI_BASE_URL=https://api.anthropic.com/v1
AI_MODEL=claude-sonnet-5-5
```

### Other providers (Gemini, Azure OpenAI, Cohere …)

Use their OpenAI-compatible endpoint if they offer one; otherwise add a new adapter class in
`backend/app/services/ai_service.py` implementing `complete(system, messages, model)` and register
it in `build_provider()`. Do not assume identical request/response formats.

### Mock mode

`AI_PROVIDER=mock` runs everything offline. Replies start with `[Mock mode]` and the UI shows a
yellow banner. **Mock mode does not verify live AI integration.**

## 2. Speech

V1 uses the browser for both directions; nothing to configure. Optional server speech
(needed for voice input in Firefox, or for higher-quality voices):

```env
SPEECH_PROVIDER=openai
SPEECH_API_KEY=<key>            # falls back to AI_API_KEY if blank
SPEECH_BASE_URL=https://api.openai.com/v1
STT_MODEL=whisper-1
TTS_MODEL=tts-1
TTS_VOICE=alloy
```

Then enable *Settings → Voice → Use server speech provider*.

## 3. Authentication

### Local development (default)

```env
AUTH_MODE=local
LOCAL_ACCESS_TOKENS=<random-token>:<any-uuid>
```

Generate a token: `py -c "import secrets;print(secrets.token_urlsafe(32))"`.
Paste the token into *Settings → General → Access token*. Multiple users:
`tokenA:uuidA,tokenB:uuidB`. Local mode is **refused** when `ENVIRONMENT=production`.

### Personal password (single owner, online)

Used by the Render deployment ([GO_ONLINE.md](GO_ONLINE.md)):

```env
AUTH_MODE=personal
OWNER_ACCESS_TOKEN=<at least 24 random characters>
OWNER_USER_ID=<your user's UUID from Supabase -> Authentication -> Users>
```

Allowed in production. The app shows an unlock screen and stores the password only on that device.

### Supabase Auth

1. Create a project at <https://supabase.com>.
2. **SQL Editor** → run `database/schema.sql` (or migrations in order).
3. **Authentication → Providers** → enable Email. Create your user (Authentication → Users).
4. **Project Settings → API**: copy the Project URL, `anon` key, `service_role` key, and
   (Project Settings → JWT/API Keys) the JWT secret if your project uses the legacy HS256 secret.
   Projects using asymmetric signing keys are verified automatically via JWKS.
5. Backend `.env`:

   ```env
   AUTH_MODE=supabase
   STORAGE_BACKEND=supabase
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_JWT_SECRET=<jwt secret>          # only for HS256 projects
   SUPABASE_SERVICE_ROLE_KEY=<service_role>  # server only!
   ```

6. Frontend `frontend/.env` (public values only):

   ```env
   VITE_SUPABASE_URL=https://<ref>.supabase.co
   VITE_SUPABASE_ANON_KEY=<anon key>
   ```

   Settings → General then shows an email/password sign-in form.

> The `service_role` key bypasses RLS. It must never appear in `frontend/`, in git, or in logs.

## 4. Endpoint reference

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/health` | GET | – | Health + configuration flags |
| `/api/chat` | POST | ✓ (rate-limited) | Message EDITH |
| `/api/voice/transcribe` | POST (multipart `audio`) | ✓ (rate-limited) | Audio → text |
| `/api/voice/speak` | POST | ✓ (rate-limited) | Text → `audio/mpeg` |
| `/api/memory` | GET / POST | ✓ | List / save approved memories |
| `/api/memory/{id}` | PATCH / DELETE | ✓ | Update / delete an owned memory |
| `/api/memory/settings` | GET / PUT | ✓ | Persistent memory on/off |
| `/api/documents` | GET / POST | ✓ | List / upload text documents |
| `/api/documents/{id}` | DELETE | ✓ | Delete an owned document |
| `/api/documents/search?q=` | GET | ✓ | Debug retrieval |
| `/api/meeting/briefing` | POST | ✓ (rate-limited) | Briefing from documents |
| `/api/meeting/summarize` | POST | ✓ (rate-limited) | Summarise notes (consent required) |

Interactive docs: <http://localhost:8000/docs> (disabled in production).

Errors are always `{"error": {"code": "...", "message": "..."}}`. Codes include
`unauthorized`, `token_expired`, `invalid_request`, `not_found`, `not_configured`,
`provider_auth`, `provider_rate_limited`, `provider_timeout`, `provider_error`,
`rate_limited`, `payload_too_large`, `memory_disabled`, `consent_required`.

### Example

```powershell
$h = @{ Authorization = "Bearer <your-token>" }
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/chat -Headers $h `
  -ContentType 'application/json' -Body '{"message":"Brief me on the backend","mode":"detailed"}'
```
