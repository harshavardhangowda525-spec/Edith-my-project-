#!/usr/bin/env python3
"""EDITH PC bridge - connects your computer to your EDITH server. Standard library only (Python 3.9+).

  python edith_bridge.py configure --server https://your-edith.onrender.com --token YOUR_OWNER_TOKEN
  python edith_bridge.py ask "why does my flutter build fail with Gradle 8?"
  python edith_bridge.py explain-error build.log        (or pipe:  npm run build 2>&1 | python edith_bridge.py explain-error -)
  python edith_bridge.py add-project shop C:\\code\\shop --test "npm test" --log logs\\app.log
  python edith_bridge.py index shop                     (incremental: only changed files are uploaded)
  python edith_bridge.py serve                          (lets EDITH run approved jobs: "run the tests on my PC")
  python edith_bridge.py install-autostart              (Windows: start the bridge by itself when you log in)
  python edith_bridge.py wake-info                      (what the phone needs to wake this laptop)

Projects can have commands EDITH may start ("run dev for shop") and commands that start when the
project is opened ("open shop on my laptop"):
  python edith_bridge.py add-project shop C:\\code\\shop --test "npm test" --cmd dev="npm run dev" --cmd build="npm run build" --open dev

"Edith, turn on my laptop and work on shop and build the login page" makes the phone wake the laptop,
then Claude Code writes the code on a NEW git branch, the tests run, and the result is reported back.
Nothing is pushed or deployed.

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
import shutil
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
    commands = {}
    for item in a.cmd or []:
        name, sep, command = item.partition("=")
        if not sep or not name.strip() or not command.strip():
            sys.exit(f'--cmd must look like name="command", got: {item}')
        commands[name.strip().lower()] = command.strip()
    for name in a.open or []:
        if name.lower() not in commands:
            sys.exit(f"--open {name}: add it with --cmd {name}=\"...\" first")
    cfg.setdefault("projects", {})[a.name] = {"path": str(path), "test": a.test, "log": a.log,
                                              "commands": commands, "open": [n.lower() for n in a.open or []]}
    save(cfg)
    print(f"Added project {a.name} -> {path}" + (f" (tests: {a.test})" if a.test else ""))
    for n, c in commands.items():
        print(f"  command {n}: {c}" + ("   (starts when the project is opened)" if n in (a.open or []) else ""))


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
    if kind == "open_project":
        return open_project(name, p)
    if kind == "run_command":
        cmd_name, command = find_command(p, params.get("command") or "")
        if not command:
            known = ", ".join(p.get("commands") or {}) or "none yet"
            return False, (f"{name} has no command called '{params.get('command')}'. Known: {known}. "
                           f'Add one with: add-project {name} PATH --cmd name="command"')
        if not approve(f"Run '{cmd_name}' for {name}: {command}", yes):
            return False, "You declined on the PC."
        print(f"Running: {command}")
        ok, out = run(command if os.name == "nt" else shlex.split(command), cwd, timeout=900, shell=os.name == "nt")
        return ok, f"{cmd_name}: " + ("finished.\n" if ok else "FAILED.\n") + out
    if kind == "agent":
        task = str(params.get("task") or "").strip()
        if not task:
            return False, "No task given."
        if not approve(f"Let Claude Code work on {name}: {task}", yes):
            return False, "You declined on the PC."
        return run_agent(cfg, job, name, p, task)
    return False, f"This bridge doesn't do '{kind}'."


def find_command(p: dict, spoken: str) -> tuple[str, str | None]:
    """Match a spoken command name ('dev server', 'Build') to a configured one ('dev', 'build')."""
    commands = p.get("commands") or {}
    key = re.sub(r"[^a-z0-9]", "", spoken.lower())
    for name, command in commands.items():
        if re.sub(r"[^a-z0-9]", "", name) == key:
            return name, command
    for name, command in commands.items():  # "dev server" -> "dev"
        n = re.sub(r"[^a-z0-9]", "", name)
        if n and (key.startswith(n) or n.startswith(key)):
            return name, command
    return spoken, None


def start_in_window(title: str, command: str, cwd: str) -> None:
    """Start a long-running command (dev server) in its own terminal window that stays open."""
    if os.name == "nt":
        subprocess.Popen(f'start "EDITH {title}" cmd /k {command}', cwd=cwd, shell=True)
    else:
        log = open(HOME / f"{re.sub(r'[^A-Za-z0-9_-]', '_', title)}.log", "ab")
        subprocess.Popen(shlex.split(command), cwd=cwd, stdout=log, stderr=log, start_new_session=True)


def open_project(name: str, p: dict) -> tuple[bool, str]:
    cwd = p["path"]
    opened = []
    code = shutil.which("code")
    if code:
        subprocess.Popen(f'"{code}" "{cwd}"' if os.name == "nt" else [code, cwd], shell=os.name == "nt")
        opened.append("VS Code")
    elif os.name == "nt":
        subprocess.Popen(["explorer", cwd])
        opened.append("the project folder (VS Code's 'code' command wasn't found)")
    for cmd_name in p.get("open") or []:
        command = (p.get("commands") or {}).get(cmd_name)
        if command:
            start_in_window(f"{name} {cmd_name}", command, cwd)
            opened.append(f"{cmd_name} ({command})")
    if not opened:
        return False, f"Couldn't open {name}: VS Code isn't installed or 'code' isn't on PATH."
    return True, f"Opened {name}: " + ", ".join(opened) + "."


def git(cwd: str, *args: str) -> tuple[bool, str]:
    return run(["git", *args], cwd, timeout=120)


def kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


AGENT_RULES = """You are working on the user's project because they asked EDITH (their voice assistant) to.
Task: {task}

Rules:
- Work only inside this repository. Do not delete unrelated files.
- Do not push, deploy, publish, install global software, or touch credentials or .env files.
- Keep the change focused on the task and match the project's existing style.
- Don't commit: EDITH saves your changes as one commit on a separate branch afterwards.
{tests}
- Finish with a short summary for the user, in plain words: what you changed, which files, and anything they
  need to do or check. This summary is read out to them, so keep it under 120 words."""


def run_agent(cfg: dict, job: dict, name: str, p: dict, task: str) -> tuple[bool, str]:
    """Claude Code writes the code on a new branch; tests run; the result is reported. Nothing is pushed."""
    cwd = p["path"]
    claude = shutil.which("claude")
    if not claude:
        return False, ("Claude Code isn't installed on this laptop (no 'claude' command). Install it from "
                       "https://claude.com/claude-code, sign in once with 'claude', then try again.")
    ok, out = git(cwd, "rev-parse", "--is-inside-work-tree")
    if not ok:
        return False, f"{name} isn't a git repository, so I can't keep the changes on a separate branch. Run 'git init' first."
    ok, status = git(cwd, "status", "--porcelain")
    dirty = [line for line in status.splitlines()[1:] if line.strip() and not line.startswith("??")]
    if dirty:
        return False, (f"{name} has uncommitted changes ({len(dirty)} files). Commit or stash them first so "
                       "EDITH's work stays separate from yours.")
    _, start_branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    start_branch = start_branch.splitlines()[-1].strip()
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower())[:40].strip("-") or "task"
    branch = f"edith/{slug}-{time.strftime('%m%d-%H%M')}"
    ok, out = git(cwd, "switch", "-c", branch)
    if not ok:
        return False, f"Couldn't create branch {branch}: {out[-300:]}"
    test = p.get("test")
    tools = ["Read", "Edit", "Write", "Glob", "Grep", "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)"]
    if test:
        tools.append(f"Bash({test}:*)")
    for command in (p.get("commands") or {}).values():
        if not re.search(r"\b(deploy|publish|push|release)\b", command):
            tools.append(f"Bash({command}:*)")
    prompt = AGENT_RULES.format(task=task, tests=f"- Run the tests with `{test}` and fix any failures you caused."
                                if test else "- There is no test command configured; check your work carefully.")
    argv = [claude, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
            "--allowedTools", *tools,
            "--disallowedTools", "Bash(git push:*)", "Bash(git reset:*)", "Bash(rm:*)", "Bash(del:*)", "WebFetch"]
    print(f"Claude Code is working on {name} (branch {branch})...")
    started = time.time()
    proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", shell=False)
    proc.stdin.write(prompt)
    proc.stdin.close()
    cancelled = False
    last_check = 0.0
    while proc.poll() is None:
        time.sleep(2)
        if time.time() - started > 3500:
            kill_tree(proc)
            return False, f"Claude Code took more than an hour on {name} and was stopped. Partial work is on branch {branch}."
        if time.time() - last_check > 10:
            last_check = time.time()
            try:
                _, state = call(cfg, "GET", f"/api/bridge/jobs/{job['id']}", timeout=15)
                if state and state.get("cancelled"):
                    kill_tree(proc)
                    cancelled = True
                    break
            except (SystemExit, OSError):
                pass  # server briefly unreachable: keep working
    stdout, stderr = proc.communicate()
    if cancelled:
        return False, f"Stopped because you cancelled it. Anything already changed is on branch {branch}."
    summary, failed = "", proc.returncode != 0
    try:
        data = json.loads(stdout.strip().splitlines()[-1])
        summary = str(data.get("result") or "").strip()
        failed = failed or bool(data.get("is_error"))
    except (ValueError, IndexError):
        summary = (stdout or stderr).strip()[-1500:]
    # Keep EDITH's work as one local commit on its branch (never pushed).
    git(cwd, "add", "-A")
    _, changed = git(cwd, "diff", "--cached", "--stat")
    changed_lines = [l for l in changed.splitlines()[1:] if l.strip()]
    if changed_lines:
        git(cwd, "-c", "user.name=EDITH", "-c", "user.email=edith@localhost", "commit", "-q", "-m", f"EDITH: {task[:72]}")
    tests_ok, test_out = True, ""
    if test and changed_lines:
        argv_t = test if os.name == "nt" else shlex.split(test)
        tests_ok, test_out = run(argv_t, cwd, shell=os.name == "nt")
    minutes = (time.time() - started) / 60
    report = [f"Claude Code {'had a problem' if failed else 'finished'} on {name} in {minutes:.0f} min."]
    if summary:
        report.append(redact(summary[:2000]))
    if changed_lines:
        report.append(f"Changes are on branch {branch} (not pushed): {changed_lines[-1].strip()}.")
        if test:
            report.append("Tests passed." if tests_ok else "Tests FAILED:\n" + test_out[-1500:])
        report.append(f"To keep it: git switch {start_branch} && git merge {branch}. "
                      f"To drop it: git switch {start_branch} && git branch -D {branch}.")
    else:
        report.append("No files were changed.")
        git(cwd, "switch", start_branch)
        git(cwd, "branch", "-D", branch)
    return (not failed and tests_ok and bool(changed_lines)) or (not failed and not changed_lines and bool(summary)), "\n".join(report)


# ---------------------------------------------------------------- wake-up support
def mac_addresses() -> list[str]:
    """Network adapter MACs (Wi-Fi first), so the phone can send the Wake-on-LAN packet."""
    macs: list[str] = []
    if os.name == "nt":
        try:
            out = subprocess.run(["getmac", "/fo", "csv", "/nh", "/v"], capture_output=True, text=True, timeout=10).stdout
            import csv
            parsed = list(csv.reader(out.splitlines()))
            parsed.sort(key=lambda r: 0 if re.search(r"wi-?fi|wireless|wlan", " ".join(r), re.I) else 1)
            for r in parsed:
                if len(r) >= 3 and re.match(r"^([0-9A-F]{2}-){5}[0-9A-F]{2}$", r[2].strip(), re.I):
                    macs.append(r[2].strip().replace("-", ":").upper())
        except (OSError, subprocess.SubprocessError):
            pass
    if not macs:
        import uuid
        n = uuid.getnode()
        if not (n >> 40) & 1:  # not a random address
            macs.append(":".join(f"{(n >> s) & 0xff:02X}" for s in range(40, -1, -8)))
    return macs[:10]


def cmd_wake_info(a) -> None:
    macs = mac_addresses()
    print("Network adapters (Wi-Fi first):", ", ".join(macs) or "none found")
    print("""
The phone learns these automatically while 'serve' runs. To let it wake this laptop from SLEEP:
 1. Device Manager > Network adapters > your Wi-Fi adapter > Power Management:
    tick 'Allow this device to wake the computer' and 'Only allow a magic packet to wake the computer'.
 2. Same adapter > Advanced: set 'Wake on Magic Packet' (and 'Wake on pattern match' if present) to Enabled.
 3. Put the laptop to SLEEP (not Shut down) and keep it plugged in. Closing the lid = sleep is fine.
 4. Phone and laptop on the same Wi-Fi. Then say: "Edith, turn on my laptop".
Not every laptop can wake over Wi-Fi. If yours can't: Settings > System > Power > 'When plugged in,
put my device to sleep after: Never' (the screen can still turn off), so EDITH can always reach it.""")


def startup_file() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/edith-bridge.cmd"


def cmd_install_autostart(a) -> None:
    load()
    if os.name != "nt":
        sys.exit("install-autostart is for Windows. On macOS/Linux add 'python3 edith_bridge.py serve --yes' "
                 "to your login items / systemd user service.")
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else Path(sys.executable)
    log = HOME / "bridge.log"
    f = startup_file()
    f.write_text(f'@echo off\r\nstart "" "{exe}" "{Path(__file__).resolve()}" serve --yes --log "{log}"\r\n', "utf-8")
    print(f"Done. The bridge now starts by itself when you log in to Windows ({f}).")
    print(f"It runs in the background without asking on the PC (you confirm on the phone). Log: {log}")
    print("Start it now without logging out: python edith_bridge.py serve --yes")


def cmd_uninstall_autostart(a) -> None:
    f = startup_file()
    if f.exists():
        f.unlink()
        print("Removed: the bridge no longer starts with Windows.")
    else:
        print("It wasn't installed.")


def cmd_serve(a) -> None:
    if a.log:
        sys.stdout = sys.stderr = open(a.log, "a", buffering=1, encoding="utf-8")
    cfg = load()
    host = socket.gethostname()
    macs = mac_addresses()
    print(f"EDITH bridge on {host} -> {cfg['server']}. Ctrl+C to stop.")
    last_beat = 0.0
    while True:
        try:
            if time.time() - last_beat > 30:
                call(cfg, "POST", "/api/bridge/heartbeat",
                     {"hostname": host, "projects": list(cfg.get("projects", {}))[:50], "version": VERSION,
                      "macs": macs})
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
        except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError, OSError, SystemExit) as e:
            # After the laptop wakes from sleep the network needs a few seconds: retry quickly, re-announce.
            print(f"Connection problem ({e}); retrying in 5 s")
            last_beat = 0.0
            time.sleep(5)


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
    c.add_argument("--cmd", action="append", help='a command EDITH may run, e.g. --cmd dev="npm run dev"')
    c.add_argument("--open", action="append", help="command names to start when the project is opened")
    c.set_defaults(fn=cmd_add_project)
    c = sub.add_parser("index"); c.add_argument("name", nargs="?"); c.set_defaults(fn=cmd_index)
    c = sub.add_parser("serve"); c.add_argument("--yes", action="store_true", help="don't ask on the PC (confirm on the phone)")
    c.add_argument("--log", help="write output to this file"); c.set_defaults(fn=cmd_serve)
    sub.add_parser("wake-info").set_defaults(fn=cmd_wake_info)
    sub.add_parser("install-autostart").set_defaults(fn=cmd_install_autostart)
    sub.add_parser("uninstall-autostart").set_defaults(fn=cmd_uninstall_autostart)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
