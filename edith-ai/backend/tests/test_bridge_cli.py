"""The PC bridge script: redaction and which files may be uploaded."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("edith_bridge", Path(__file__).parents[2] / "tools" / "edith_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_redacts_credentials():
    text = ("Authorization: Bearer abcdefghijklmnop\nGROQ=gsk_abcdefghijklmnopqrst\npassword = hunter22222\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----")
    out = bridge.redact(text)
    for secret in ("abcdefghijklmnop", "gsk_abcdefghijklmnopqrst", "hunter22222", "MIIabc"):
        assert secret not in out
    assert "[REDACTED]" in out


def test_secret_files_are_never_indexed():
    for name in (".env", ".env.local", "server.pem", "google-services.json", "service-account.json", "id_rsa"):
        assert bridge.SECRET_FILES.search(name), name
    for name in ("main.py", "app.tsx", "README.md"):
        assert not bridge.SECRET_FILES.search(name), name


def test_index_is_incremental(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "HOME", tmp_path / "home")
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "a.py").write_text("print(1)\n")
    (tmp_path / "p" / ".env").write_text("KEY=x\n")
    (tmp_path / "p" / "node_modules").mkdir()
    (tmp_path / "p" / "node_modules" / "lib.js").write_text("x")
    calls = []

    def fake_call(cfg, method, path, body=None, timeout=60):
        calls.append((method, path, (body or {}).get("title")))
        return 201, {"id": f"doc{len(calls)}"}
    monkeypatch.setattr(bridge, "call", fake_call)
    cfg = {"projects": {"p": {"path": str(tmp_path / "p")}}}
    assert "1 new or changed" in bridge.index_project(cfg, "p", log=lambda m: None)
    assert calls == [("POST", "/api/documents", "code:p/a.py")]
    calls.clear()
    assert "0 new or changed" in bridge.index_project(cfg, "p", log=lambda m: None) and calls == []
    (tmp_path / "p" / "a.py").write_text("print(2)\n")
    bridge.index_project(cfg, "p", log=lambda m: None)
    assert [c[0] for c in calls] == ["DELETE", "POST"]  # old version replaced
    calls.clear()
    (tmp_path / "p" / "a.py").unlink()
    bridge.index_project(cfg, "p", log=lambda m: None)
    assert [c[0] for c in calls] == ["DELETE"]


def test_unknown_job_and_missing_test_command_are_refused():
    cfg = {"projects": {"p": {"path": "."}}}
    assert bridge.handle(cfg, {"kind": "rm_rf", "params": {}}, yes=True)[0] is False
    ok, msg = bridge.handle(cfg, {"kind": "run_tests", "params": {}}, yes=True)
    assert not ok and "No test command" in msg


# ---------------------------------------------------------------- laptop jobs
import os
import subprocess
import sys
import textwrap


def _repo(tmp_path):
    repo = tmp_path / "shop"
    repo.mkdir()
    (repo / "app.py").write_text("print('hi')\n")
    (repo / "test_app.py").write_text("def test_ok():\n    assert True\n")
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True)
    return repo


def _fake_claude(tmp_path, monkeypatch, body):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return exe


def _cfg(repo, test=True):
    return {"server": "http://x", "token": "t", "projects": {"shop": {
        "path": str(repo), "test": f"{sys.executable} -m pytest -q -p no:cacheprovider" if test else None,
        "commands": {"dev": "echo dev-server-running", "deploy": "echo deploy"}, "open": []}}}


def test_agent_writes_code_on_a_new_branch_and_runs_tests(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _fake_claude(tmp_path, monkeypatch, """
        import json, sys
        prompt = sys.stdin.read()
        assert "Do not push" in prompt and "add a greeting" in prompt
        args = sys.argv[1:]
        assert "Bash(git push:*)" in args[args.index("--disallowedTools"):]
        assert "Bash(echo deploy:*)" not in args  # deploy-like commands are never allowed
        open("greet.py", "w").write("def greet():\\n    return 'hello'\\n")
        print(json.dumps({"result": "Added greet() in greet.py.", "is_error": False}))
    """)
    monkeypatch.setattr(bridge, "call", lambda *a, **k: (200, {"cancelled": False}))
    ok, report = bridge.handle(_cfg(repo), {"id": "j1", "kind": "agent",
                                            "params": {"project": "shop", "task": "add a greeting"}}, yes=True)
    assert ok, report
    assert "Added greet()" in report and "Tests passed." in report and "not pushed" in report
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, capture_output=True,
                            text=True).stdout.strip()
    assert branch.startswith("edith/add-a-greeting")
    main_files = subprocess.run(["git", "ls-tree", "--name-only", "main"], cwd=repo, capture_output=True,
                                text=True).stdout.split()
    assert "greet.py" not in main_files  # main is untouched


def test_agent_refuses_uncommitted_changes_and_missing_claude(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(bridge.shutil, "which", lambda name: None)
    ok, msg = bridge.handle(_cfg(repo), {"id": "j", "kind": "agent", "params": {"task": "do something"}}, yes=True)
    assert not ok and "isn't installed" in msg
    monkeypatch.undo()
    _fake_claude(tmp_path, monkeypatch, "print('{}')\n")
    (repo / "app.py").write_text("changed\n")
    ok, msg = bridge.handle(_cfg(repo), {"id": "j", "kind": "agent", "params": {"task": "do something"}}, yes=True)
    assert not ok and "uncommitted changes" in msg


def test_agent_stops_when_task_is_cancelled(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    _fake_claude(tmp_path, monkeypatch, "import time, sys\nsys.stdin.read()\ntime.sleep(60)\n")
    monkeypatch.setattr(bridge, "call", lambda *a, **k: (200, {"cancelled": True}))
    ok, msg = bridge.handle(_cfg(repo), {"id": "j", "kind": "agent", "params": {"task": "slow work"}}, yes=True)
    assert not ok and "cancelled" in msg


def test_run_named_command_and_unknown_command(tmp_path):
    repo = _repo(tmp_path)
    ok, out = bridge.handle(_cfg(repo), {"kind": "run_command", "params": {"command": "dev server"}}, yes=True)
    assert ok and "dev-server-running" in out
    ok, out = bridge.handle(_cfg(repo), {"kind": "run_command", "params": {"command": "rm everything"}}, yes=True)
    assert not ok and "no command called" in out


def test_wake_info_finds_a_mac():
    macs = bridge.mac_addresses()
    assert all(len(m) == 17 for m in macs)
