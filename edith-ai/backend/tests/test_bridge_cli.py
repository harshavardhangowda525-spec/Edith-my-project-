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
