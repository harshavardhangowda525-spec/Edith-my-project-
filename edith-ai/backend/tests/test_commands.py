"""Spoken sentence -> phone action."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ai_service import Completion
from app.services.command_service import describe, parse_command, validate_action
from tests.conftest import auth, make_settings

FAV = {"type": "play_music", "query": "", "favorite": True}


@pytest.mark.parametrize("said, expected", [
    # calls
    ("Call mom.", {"type": "call", "contact": "mom"}),
    ("Edith, call Rahul Sharma please", {"type": "call", "contact": "rahul sharma"}),
    ("Can you call my wife?", {"type": "call", "contact": "my wife"}),
    ("Make a call to Dad", {"type": "call", "contact": "dad"}),
    ("Phone Priya on her mobile", {"type": "call", "contact": "priya"}),
    ("Give Arjun a call", {"type": "call", "contact": "arjun"}),
    # music (the user's own example first)
    ("Open Spotify and play my favorite music", {**FAV, "app": "spotify"}),
    ("open spotify and play my favourite songs", {**FAV, "app": "spotify"}),
    ("Play my favourite music", {**FAV, "app": None}),
    ("Play Arijit Singh on Spotify", {"type": "play_music", "query": "arijit singh", "favorite": False, "app": "spotify"}),
    ("play shape of you", {"type": "play_music", "query": "shape of you", "favorite": False, "app": None}),
    ("Play some music", {**FAV, "app": None}),
    ("play lo-fi beats on youtube music", {"type": "play_music", "query": "lo-fi beats", "favorite": False, "app": "youtube_music"}),
    # media
    ("Pause.", {"type": "media", "command": "pause"}),
    ("pause the music", {"type": "media", "command": "pause"}),
    ("Next song", {"type": "media", "command": "next"}),
    ("skip this song", {"type": "media", "command": "next"}),
    ("previous track", {"type": "media", "command": "previous"}),
    ("turn it up", {"type": "media", "command": "volume_up"}),
    ("Volume down", {"type": "media", "command": "volume_down"}),
    ("resume", {"type": "media", "command": "resume"}),
    ("play", {"type": "media", "command": "play"}),
    # alarms / timers
    ("Set an alarm for 6 AM", {"type": "alarm", "hour": 6, "minute": 0, "label": None}),
    ("wake me up at 6:30 a.m. tomorrow", {"type": "alarm", "hour": 6, "minute": 30, "label": None}),
    ("Set alarm for 7.15 pm", {"type": "alarm", "hour": 19, "minute": 15, "label": None}),
    ("alarm at 12 am", {"type": "alarm", "hour": 0, "minute": 0, "label": None}),
    ("Set a timer for 10 minutes", {"type": "timer", "seconds": 600}),
    ("timer for thirty seconds", {"type": "timer", "seconds": 30}),
    ("set a 5 minute timer", {"type": "timer", "seconds": 300}),
    ("timer for 1 hour", {"type": "timer", "seconds": 3600}),
    # navigation / apps
    ("Navigate to the airport", {"type": "navigate", "destination": "airport"}),
    ("take me home", {"type": "navigate", "destination": "home"}),
    ("directions to MG Road", {"type": "navigate", "destination": "mg road"}),
    ("Open Instagram", {"type": "open_app", "app": "instagram"}),
    ("launch the camera app", {"type": "open_app", "app": "camera"}),
    ("Edith open WhatsApp", {"type": "open_app", "app": "whatsapp"}),
])
def test_parse_commands(said, expected):
    assert parse_command(said) == expected


@pytest.mark.parametrize("said", [
    "What is a database?",
    "How do I explain Kubernetes to a client?",
    "Tell me a joke",
    "What's the capital of Japan",
    "Who called the meeting yesterday?",
    "Why do people play cricket?",
    "How does the stop loss work in trading?",
])
def test_questions_are_not_commands(said):
    assert parse_command(said) is None


def test_validate_rejects_bad_actions():
    assert validate_action({"type": "rm -rf"}) is None
    assert validate_action({"type": "alarm", "hour": 25, "minute": 0}) is None
    assert validate_action({"type": "timer", "seconds": -5}) is None
    assert validate_action({"type": "media", "command": "format_phone"}) is None
    assert validate_action({"type": "call", "contact": ""}) is None
    assert validate_action({"type": "play_music", "query": "x", "app": "evil"})["app"] is None


def test_describe():
    assert describe({"type": "alarm", "hour": 18, "minute": 5, "label": None}) == "Alarm set for 6:05 PM."
    assert describe({"type": "call", "contact": "mom"}) == "Calling mom."
    assert describe({"type": "timer", "seconds": 600}) == "Timer set for 10 minutes."


class ScriptedProvider:
    name = "test"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def complete(self, system, messages, model):
        self.calls.append(messages[-1]["content"])
        return Completion(text=self.replies.pop(0), model=model, provider="test", mock=False)


def _client(replies):
    app = create_app(make_settings())
    p = ScriptedProvider(replies)
    app.state.ai._provider = p
    return TestClient(app), p


def test_assistant_endpoint_action_without_ai_call():
    c, p = _client([])
    r = c.post("/api/assistant", headers=auth(), json={"message": "Open Spotify and play my favorite music"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "action"
    assert body["action"] == {**FAV, "app": "spotify"}
    assert body["say"] == "Playing your favourite music."
    assert p.calls == []  # handled by fast patterns


def test_assistant_endpoint_ai_fallback_for_unusual_phrasing():
    c, p = _client(['{"type":"call","contact":"mom"}'])
    r = c.post("/api/assistant", headers=auth(), json={"message": "I need to ring up my mom real quick"})
    assert r.json()["kind"] == "action" and r.json()["action"] == {"type": "call", "contact": "mom"}


def test_assistant_endpoint_answers_questions():
    c, p = _client(["A database stores data."])
    r = c.post("/api/assistant", headers=auth(), json={"message": "What is a database?"})
    assert r.json() == {"kind": "answer", "action": None, "say": None, "reply": "A database stores data.",
                        "model": r.json()["model"], "mock": False, "sources": []}


def test_assistant_endpoint_ai_says_none_then_answers():
    c, p = _client(['{"type":"none"}', "Cricket is popular because..."])
    r = c.post("/api/assistant", headers=auth(), json={"message": "Why do people play cricket so much?"})
    assert r.json()["kind"] == "answer" and r.json()["reply"].startswith("Cricket")


def test_assistant_endpoint_ignores_malicious_ai_json():
    c, p = _client(['{"type":"shell","cmd":"rm"}', "fallback answer"])
    r = c.post("/api/assistant", headers=auth(), json={"message": "do that music thing I said"})
    assert r.json()["kind"] == "answer"


def test_assistant_requires_auth():
    c, _ = _client([])
    assert c.post("/api/assistant", json={"message": "call mom"}).status_code == 401
