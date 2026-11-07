# EDITH speed & intelligence upgrade — technical report

This upgrade keeps everything EDITH already did (wake word, calls, apps, music, WhatsApp, Gmail, leads,
meeting mode, the holographic orb) and makes it faster, more reliable, and useful for development work.

## 1. What changed

### Latency
| Change | Where | Effect |
|---|---|---|
| **Streaming answers** (server-sent events) | `POST /api/assistant/stream`, `POST /api/voice/ask` | The first words arrive as soon as the model writes them, not when the whole answer is done |
| **One round trip for voice** | `/api/voice/ask`: audio in → transcript + streamed answer out | The phone no longer waits for a transcript and then sends a second request |
| **Speak while streaming** | Android `StreamingSpeaker`, web `speakQueued` | EDITH starts talking after the first full sentence |
| **Model routing** | `services/router.py` | Quick questions → fast model, coding/detail → balanced (`AI_MODEL`), hard design/debugging → deep model. Override per request (`route`) or in the web command palette |
| **Connection reuse** | `services/http.py` (pooled HTTP/1.1 keep-alive client); Android keeps connections alive | No new TLS handshake per request |
| **Parallel context** | memory + document search run at the same time | |
| **Caching** | memory prompt and document chunks (60 s, cleared on every change); repeat answers for stateless, non-time-sensitive quick questions | |
| **Instant local answers** | `services/quick.py` | Maths, unit conversions, time/date/battery from the phone answer in ~1 ms with no AI call |
| **Keep-warm** | Android pings the server every 9 min while listening | Avoids most Render free-plan cold starts |
| **Interruptible speech** | say "stop" or "Edith" while EDITH talks (barge-in); web: Stop button / Esc | |

### Reliability
* **Fallbacks:** if a model fails (rate limit, timeout, error) **before** the first word, EDITH retries on the
  next model in the route's fallback order. It never switches models half way through an answer.
* **Circuit breakers:** a model that fails 3 times in a row (or hits a rate limit) is skipped for 20–30 s.
* **Route timeouts:** fast 12 s, balanced 30 s, deep 60 s (configurable).
* **Prompt-injection protection:** document excerpts are wrapped in `<document>` tags, marked as untrusted
  data, and a document can't close its own wrapper. Spoken commands from overheard speech without "Edith" can
  only match exact phrases, never AI-guessed actions.
* **Secret redaction** in logs (server) and in everything the PC bridge uploads.
* **Structured logs:** `LOG_FORMAT=json` writes one JSON object per line.

### Intelligence & integrations
* **Project memory:** say "remember that …" or "remember for project shop: …". EDITH sorts it into a category
  (decision, error fix, preference, task, command, project, general). "What do you remember about project
  shop?" reads it back. View, correct, re-categorise and delete in the web app (Settings → Memory).
* **Background tasks** (`services/tasks.py`): run concurrently (3 workers), by priority, with
  cancel/pause/resume/retry, progress, retries with exponential backoff (2 s, 4 s…) for temporary provider
  errors, timeouts, crash recovery (unfinished tasks are re-queued after a restart when Supabase is used), and
  persistent history (`tasks` table). **A task is only "completed" when its handler returned a real result.**
  Task types: `research` (deep model), `summarize_document`, `github_summary`, `pc`.
* **PC bridge** (`tools/edith_bridge.py`, see [PC_BRIDGE.md](PC_BRIDGE.md)): streaming `ask`,
  `explain-error`, incremental project indexing, and approved jobs (tests, git status/log/diff, logs).
* **GitHub intelligence:** open PRs, newest issues and CI failures from the GitHub API (`GITHUB_TOKEN`).
* **Web app:** streaming answers with a live caret, new orb states (Understanding → Processing → Speaking /
  Executing → Completed / Error), model and timing under each answer, **Ctrl+K command palette**, Tasks & System
  drawer (live p50/p95/p99, cache hit rate, models, circuit breakers, PC bridge status), drag-and-drop files
  into your documents, minimal mode, desktop notifications when tasks finish.
* **Phone:** when EDITH starts a background task it keeps listening; you get a notification with the real
  result, and EDITH tells you in your headphones (not during a call or meeting).

## 2. Benchmark (measured, 106 requests)

`backend/bench/run_bench.py` runs EDITH under a real uvicorn server against `bench/fake_upstream.py`, a fake
AI/speech provider with **fixed, stated delays**, so before and after are compared under identical conditions:

| Assumption | Value |
|---|---|
| New connection (TLS + round trip) | 150 ms |
| Time to first token | small model 150 ms · large 450 ms · reasoning 900 ms |
| Generation speed | small 900 · large 300 · reasoning 250 tokens/s |
| Speech-to-text | 250 ms |

Requests: 40 simple questions, 40 coding questions, 20 phone commands, 6 voice questions (audio).
"Before" is the previous commit run on the same harness. Times in milliseconds.

**Time until the first words reach the client** (p50 / p95 / p99):

| Request type | Before | After |
|---|---|---|
| Simple questions (40) | 728 / 739 / 739 | **158 / 458 / 458** |
| Coding questions (40) | 730 / 1600 / 1605 | **458 / 908 / 909** |
| Phone commands (20) | 4 / 6 / 11 | 3 / 8 / 9 |
| Voice questions (6) | 1157 / 1167 / 1167 | **429 / 433 / 433** |
| All (106) | 727 / 1158 / 1604 | **159 / 906 / 909** |

**Time until the full answer** (after): all requests p50 196 / p95 1179 / p99 1234 ms (before: the same as
first words, 727 / 1158 / 1604, since nothing streamed).

Raw results: `bench/results/before.json`, `after-speed-core.json`, `final.json` (after all features).

**What these numbers are not:** they are not measurements of Groq, Render or your phone. Real numbers depend on
the provider's speed, your network, and Render's free-plan cold start (30–60 s after ~15 idle minutes).
Your real latency is measured live by the server: web app → ☰ → System, or `GET /api/metrics`, and each answer
in the web app shows its own "first words … ms".

## 3. Configuration

All optional; defaults work.

| Variable | Default | Meaning |
|---|---|---|
| `AI_ROUTING` | `auto` | `auto` = route per question, `off` = always `AI_MODEL` |
| `AI_MODEL_FAST` | provider preset (Groq: `llama-3.1-8b-instant`) | quick questions |
| `AI_MODEL` | provider preset (Groq: `llama-3.3-70b-versatile`) | balanced: coding, detail |
| `AI_MODEL_DEEP` | provider preset (Groq: `openai/gpt-oss-120b`) | hard problems, research tasks |
| `ROUTE_TIMEOUT_FAST` / `_BALANCED` / `_DEEP` | 12 / 30 / 60 s | per-route timeouts |
| `AI_PRICES_PER_MTOK` | – | JSON `{"model": [input, output]}` USD per 1M tokens, for the cost estimate in metrics |
| `GITHUB_TOKEN`, `GITHUB_DEFAULT_REPO` | – | GitHub summaries |
| `TASK_WORKERS` | 3 | concurrent background tasks |
| `BRIDGE_JOB_TIMEOUT_S` | 900 | how long a PC job may take |
| `LOG_FORMAT` | `text` | `json` for structured logs |

Supabase users: run `database/migrations/0003_tasks.sql` once for task history.

## 4. Tests

* Backend: `cd backend && python -m pytest -q` (covers streaming, routing, fallback, circuit breakers,
  caching, quick answers, metrics, task engine, PC bridge round trip, GitHub summary, prompt-injection
  wrapping, spoken memory/task commands, and the bridge script's redaction and incremental indexing).
* Android: `./gradlew testStandardReleaseUnitTest` (streaming SSE reading, barge-in, sentence splitting,
  contacts, messaging, headphones).
* Benchmark: `cd backend && python -m bench.run_bench --label mine --out bench/results/mine.json`.

## 5. Known limitations

* Not tested against live Groq or on a real phone in this upgrade; the numbers above come from the simulated
  provider. Use the System panel to see your real numbers.
* Render free plan cold starts still happen if the phone isn't listening (keep-warm only runs while it is).
* Without Supabase (`STORAGE_BACKEND=memory`), tasks and memories are lost on restart.
* Screen awareness and multi-agent coordination were not added: screen reading needs an explicit permission
  flow on each device and wasn't safe to ship untested. Voice-to-code edits are not applied automatically;
  `explain-error` returns a suggested patch for you to review and apply.
* The phone's streaming speech uses the phone's voice; the optional Groq human voice is per sentence and
  subject to Groq's rate limits.
