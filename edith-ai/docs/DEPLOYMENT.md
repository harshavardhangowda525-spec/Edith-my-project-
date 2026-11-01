# Deployment

## Local (Windows)

See the README quick start, or run `scripts\setup.ps1 -Start`.

## Using it with earbuds and an Android phone

1. **Windows PC:** pair the earbuds (Settings → Bluetooth & devices). In Settings → System →
   Sound, choose the earbuds as both *Output* and *Input*. Open <http://localhost:5173> in
   Chrome/Edge, hold **Hold to talk** (or Space).
2. **Android phone on the same Wi-Fi:** microphone access needs HTTPS on non-localhost
   origins, so either
   * deploy with HTTPS (below), or
   * temporarily expose your dev servers through an HTTPS tunnel (e.g. Cloudflare Tunnel),
     add the tunnel origin to `CORS_ORIGINS`, and set the API URL in Settings.
   Pair the earbuds with the phone; Android routes Chrome's mic/speaker to them automatically
   when connected.

## Docker

```powershell
cd edith-ai
copy backend\.env.example backend\.env   # then edit
docker compose up --build
```

* Frontend: <http://localhost:8080> · Backend: <http://localhost:8000>
* `VITE_API_URL` is a **build-time** value: `$env:VITE_API_URL="https://api.example.com"; docker compose build frontend`.
* The backend container runs as a non-root user with a read-only filesystem.

## Production on an existing server

1. Use `ENVIRONMENT=production`, `AUTH_MODE=supabase`, `STORAGE_BACKEND=supabase`.
   (Local tokens are refused and `/docs` is disabled in production.)
2. **HTTPS is mandatory** — browsers block the microphone on plain HTTP and tokens must not
   travel in clear text. Put a TLS reverse proxy in front:

   ```caddyfile
   edith.example.com {
     reverse_proxy frontend:80
   }
   api.edith.example.com {
     reverse_proxy backend:8000
     request_body {
       max_size 12MB
     }
   }
   ```

   Caddy obtains certificates automatically. With nginx, use Let's Encrypt/certbot.
3. `CORS_ORIGINS=https://edith.example.com` — exact origins only, never `*`.
4. Build the frontend with `VITE_API_URL=https://api.edith.example.com`.
5. Keep `backend/.env` readable only by the service account (`chmod 600`), or use your
   platform's secret manager. Rotate keys if they are ever exposed.
6. The built-in rate limiter is per-process. With multiple replicas, rate-limit at the proxy or
   gateway as well.
7. Monitor `GET /health`. Logs redact bearer tokens and API-key-like strings, but avoid logging
   request bodies.

## Security checklist

- [ ] HTTPS everywhere; HSTS is sent automatically in production.
- [ ] No secrets in `frontend/.env`, the repo, or Docker images.
- [ ] Supabase RLS enabled (schema does this) and service-role key on the server only.
- [ ] `CORS_ORIGINS` lists only your frontend origin(s).
- [ ] `RATE_LIMIT_PER_MINUTE` and provider-side spend limits configured.
- [ ] Backups enabled in Supabase.
