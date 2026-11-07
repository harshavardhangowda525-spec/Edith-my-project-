#!/usr/bin/env python3
"""EDITH PC bridge - connects your computer to your EDITH server. Standard library only (Python 3.9+).

  python edith_bridge.py configure --server https://your-edith.onrender.com --token YOUR_OWNER_TOKEN
  python edith_bridge.py ask "why does my flutter build fail with Gradle 8?"
  python edith_bridge.py explain-error build.log        (or pipe:  npm run build 2>&1 | python edith_bridge.py explain-error -)
  python edith_bridge.py add-project shop C:\\code\\shop --test "npm test" --log logs\\app.log
  python edith_bridge.py index shop                     (incremental: only changed files are uploaded)
  python edith_bridge.py serve                          (lets EDITH run approved jobs: "run the tests on my PC")

Safety:
  * EDITH can only ask for a fixed list of jobs (tests, git status/log/diff, tail a log, index, list projects).
    There is no "run any command" job. Test commands are the ones YOU configured with add-project.
  * Running tests and indexing ask you on this PC first (y/N) unless you start serve with --yes.
  * Nothing that deletes, pushes, deploys or installs is ever run by the bridge.
  * Secrets (.env, keys, tokens) are never uploaded; obvious credentials are redacted from any output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("EDITH_HOME", Path.home() / ".edith"))
CONFIG = HOME / "bridge.json"
VERSION = "1"

CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".dart", ".kt", ".kts", ".java", ".go", ".rs", ".rb", ".php",
            ".cs", ".cpp", ".c", ".h", ".swift", ".sql", ".md", ".yaml", ".yml", ".toml", ".json", ".gradle",
            ".html", ".css", ".scss", ".vue", ".svelte", ".sh", ".ps1", ".txt"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "build", "dist", ".dart_tool",
             ".gradle", ".idea", ".next", ".nuxt", "out", "target", "coverage", ".pytest_cache", "Pods",
             ".expo", "vendor", "bin", "obj"}
SECRET_FILES = re.compile(r"(^\.env(\..*)?$|\.pem$|\.key$|\.p12$|\.jks$|\.keystore$|id_rsa|credentials|secret|"
                          r"service-account|google-services\.json$|GoogleService-Info\.plist$)", re.I)
MAX_FILE = 150_000
REDACT = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\b(sk-|gsk_|ghp_|github_pat_|xox[bap]-|AIza)[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
    re.compile(r"(?i)((?:api[_-]?key|secret|password|passwd|token)\s*[=:]\s*)['\"]?[^\s'\",]{6,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
]


def redact(text: str) -> str:
    for p in REDACT:
        text = p.sub(lambda m: (m.group(1) if m.groups() and m.group(1) else "") + "[REDACTED]", text)
    return text


# ---------------------------------------------------------------- config & HTTP
def load() -> dict:
    if not CONFIG.exists():
        sys.exit("Not configured. Run: python edith_bridge.py configure --server URL --token TOKEN")
    return json.loads(CONFIG.read_text("utf-8"))


def save(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), "utf-8")
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass


def request(cfg: dict, method: str, path: str, body: dict | None = None, timeout: float = 60):
    req = urllib.request.Request(cfg["server"].rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {cfg['token']}",
                                          "Content-Type": "application/json", "User-Agent": "edith-bridge"})
    return urllib.request.urlopen(req, timeout=timeout)


def call(cfg: dict, method: str, path: str, body: dict | None = None, timeout: float = 60):
    try:
        with request(cfg, method, path, body, timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())["error"]["message"]
        except Exception:
            msg = str(e)
        raise SystemExit(f"EDITH server error {e.code}: {msg}")


def stream_answer(cfg: dict, message: str, route: str = "auto") -> str:
    body = {"message": message[:4000], "mode": "detailed", "route": route, "use_documents": True}
    out = []
    try:
        with request(cfg, "POST", "/api/assistant/stream", body, timeout=120) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                if ev["type"] == "token":
                    print(ev["t"], end="", flush=True)
                    out.append(ev["t"])
                elif ev["type"] == "error":
                    print(f"\n[error] {ev.get('message')}")
                elif ev["type"] == "done":
                    t = ev.get("timings", {})
                    print(f"\n\n[{ev.get('model') or ev.get('route')}, first words {t.get('first_token_ms', '?')} ms, "
                          f"total {t.get('total_ms', '?')} ms]")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"EDITH server error {e.code}")
    return "".join(out)


# ---------------------------------------------------------------- commands
def cmd_configure(a) -> None:
    cfg = json.loads(CONFIG.read_text("utf-8")) if CONFIG.exists() else {"projects": {}}
    cfg.update(server=a.server.rstrip("/"), token=a.token.strip())
    save(cfg)
    status, health = call(cfg, "GET", "/health")
    print(f"Saved to {CONFIG}. Server says: {health.get('status')}, AI: {health.get('ai_provider')} {'(mock - not a real AI)' if health.get('mock_mode') else ''}")


def cmd_ask(a) -> None:
    stream_answer(load(), " ".join(a.question), a.route)


def cmd_explain(a) -> None:
    text = sys.stdin.read() if a.file == "-" else Path(a.file).read_text("utf-8", "replace")
    text = redact(text)[-3500:]  # the end of a log is where the error is
    stream_answer(load(), "Explain this error in plain words, find the most likely cause and give the exact fix "
                          "(commands or a code patch). Error output:\n```\n" + text + "\n```", "balanced")


def cmd_add_project(a) -> None:
    cfg = load()
    path = Path(a.path).expanduser().resolve()
    if not path.is_dir():
        sys.exit(f"{path} is not a folder")
    cfg.setdefault("projects", {})[a.name] = {"path": str(path), "test": a.test, "log": a.log}
    save(cfg)
    print(f"Added project {a.name} -> {path}" + (f" (tests: {a.test})" if a.test else ""))


def project(cfg: dict, name: str | None) -> tuple[str, dict]:
    projects = cfg.get("projects", {})
    if not projects:
        raise RuntimeError("No projects yet. On the PC run: python edith_bridge.py add-project NAME PATH --test CMD")
    if not name:
        if len(projects) == 1:
            return next(iter(projects.items()))
        raise RuntimeError(f"Which project? I know: {', '.join(projects)}")
    for key, p in projects.items():
        if key.lower() == name.lower().strip():
            return key, p
    raise RuntimeError(f"I don't know a project called {name}. I know: {', '.join(projects)}")


def index_project(cfg: dict, name: str | None, log=print) -> str:
    name, p = project(cfg, name)
    root = Path(p["path"])
    HOME.mkdir(parents=True, exist_ok=True)
    state_file = HOME / f"index-{re.sub(r'[^A-Za-z0-9_-]', '_', name)}.json"
    state = json.loads(state_file.read_text("utf-8")) if state_file.exists() else {}
    seen, added, unchanged, removed, skipped = set(), 0, 0, 0, 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            f = Path(dirpath) / fn
            rel = f.relative_to(root).as_posix()
            if f.suffix.lower() not in CODE_EXT or SECRET_FILES.search(fn):
                continue
            try:
                if f.stat().st_size > MAX_FILE:
                    skipped += 1
                    continue
                content = f.read_text("utf-8")
            except (OSError, UnicodeDecodeError):
                skipped += 1
                continue
            seen.add(rel)
            digest = hashlib.sha256(content.encode()).hexdigest()
            old = state.get(rel)
            if old and old["sha"] == digest:
                unchanged += 1
                continue
            if old:
                call(cfg, "DELETE", f"/api/documents/{old['doc']}")
            if not content.strip():
                state.pop(rel, None)
                continue
            _, doc = call(cfg, "POST", "/api/documents",
                          {"title": f"code:{name}/{rel}"[:200], "content": f"File {rel} in project {name}:\n\n" +
                           redact(content)})
            state[rel] = {"sha": digest, "doc": doc["id"]}
            added += 1
            state_file.write_text(json.dumps(state), "utf-8")
    for rel in [r for r in state if r not in seen]:
        call(cfg, "DELETE", f"/api/documents/{state.pop(rel)['doc']}")
        removed += 1
    state_file.write_text(json.dumps(state), "utf-8")
    msg = (f"Indexed {name}: {added} new or changed files uploaded, {unchanged} unchanged, {removed} removed, "
           f"{skipped} skipped (too big or binary).")
    log(msg)
    return msg


def cmd_index(a) -> None:
    try:
        index_project(load(), a.name)
    except RuntimeError as e:
        sys.exit(str(e))


def run(cmd: list[str] | str, cwd: str, timeout: int = 900, shell: bool = False) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=shell,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError as e:
        return False, f"Command not found: {e.filename}"
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {timeout} s"
    out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    out = redact(out.strip())
    if len(out) > 12000:
        out = out[:2000] + "\n...\n" + out[-9000:]
    return r.returncode == 0, f"exit code {r.returncode}\n{out}"


def approve(question: str, auto: bool) -> bool:
    if auto:
        return True
    print(f"\nEDITH asks: {question}")
    try:
        return input("Allow? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def handle(cfg: dict, job: dict, yes: bool) -> tuple[bool, str]:
    kind, params = job["kind"], job.get("params") or {}
    if kind == "list_projects":
        ps = cfg.get("projects", {})
        return True, ("Projects: " + ", ".join(f"{k} ({v['path']})" for k, v in ps.items())) if ps else "No projects."
    try:
        name, p = project(cfg, params.get("project"))
    except RuntimeError as e:
        return False, str(e)
    cwd = p["path"]
    if kind == "git_status":
        return run(["git", "status", "--short", "--branch"], cwd)
    if kind == "git_log":
        return run(["git", "log", "--oneline", "-n", "15"], cwd)
    if kind == "git_diff":
        return run(["git", "diff", "--stat"], cwd)
    if kind == "tail_log":
        if not p.get("log"):
            return False, f"No log file set for {name}. Use add-project ... --log PATH"
        f = Path(cwd) / p["log"]
        try:
            return True, redact("\n".join(f.read_text("utf-8", "replace").splitlines()[-80:]))
        except OSError as e:
            return False, f"Can't read {f}: {e}"
    if kind == "run_tests":
        if not p.get("test"):
            return False, f"No test command set for {name}. Use add-project ... --test \"npm test\""
        if not approve(f"Run tests for {name}: {p['test']}", yes):
            return False, "You declined on the PC."
        print(f"Running: {p['test']}")
        argv = p["test"] if os.name == "nt" else shlex.split(p["test"])
        ok, out = run(argv, cwd, shell=os.name == "nt")
        return ok, ("Tests passed.\n" if ok else "Tests FAILED.\n") + out
    if kind == "index_project":
        if not approve(f"Upload changed source files of {name} to your EDITH knowledge base", yes):
            return False, "You declined on the PC."
        return True, index_project(cfg, name)
    return False, f"This bridge doesn't do '{kind}'."


def cmd_serve(a) -> None:
    cfg = load()
    host = socket.gethostname()
    print(f"EDITH bridge on {host} -> {cfg['server']}. Ctrl+C to stop.")
    last_beat = 0.0
    while True:
        try:
            if time.time() - last_beat > 30:
                call(cfg, "POST", "/api/bridge/heartbeat",
                     {"hostname": host, "projects": list(cfg.get("projects", {}))[:50], "version": VERSION})
                last_beat = time.time()
            status, job = call(cfg, "GET", "/api/bridge/jobs/next?wait=20", timeout=40)
            if status == 204 or not job:
                continue
            print(f"\nJob: {job['kind']} {job.get('params') or ''}")
            ok, output = handle(cfg, job, a.yes)
            print(("OK" if ok else "FAILED") + ": " + output[:300])
            call(cfg, "POST", f"/api/bridge/jobs/{job['id']}/result", {"ok": ok, "output": output[:60000]})
        except KeyboardInterrupt:
            print("\nBye.")
            return
        except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError) as e:
            print(f"Connection problem ({e}); retrying in 10 s")
            time.sleep(10)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="EDITH PC bridge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("configure"); c.add_argument("--server", required=True); c.add_argument("--token", required=True)
    c.set_defaults(fn=cmd_configure)
    c = sub.add_parser("ask"); c.add_argument("question", nargs="+")
    c.add_argument("--route", default="auto", choices=["auto", "fast", "balanced", "deep"]); c.set_defaults(fn=cmd_ask)
    c = sub.add_parser("explain-error"); c.add_argument("file", help="log file, or - for stdin"); c.set_defaults(fn=cmd_explain)
    c = sub.add_parser("add-project"); c.add_argument("name"); c.add_argument("path")
    c.add_argument("--test", help='test command, e.g. "npm test" or "flutter test"'); c.add_argument("--log")
    c.set_defaults(fn=cmd_add_project)
    c = sub.add_parser("index"); c.add_argument("name", nargs="?"); c.set_defaults(fn=cmd_index)
    c = sub.add_parser("serve"); c.add_argument("--yes", action="store_true", help="don't ask before tests/indexing")
    c.set_defaults(fn=cmd_serve)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
