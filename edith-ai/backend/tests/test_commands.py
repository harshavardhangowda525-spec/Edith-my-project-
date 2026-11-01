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


# --- conversation mode ------------------------------------------------------------

from app.services.command_service import followup_kind  # noqa: E402


@pytest.mark.parametrize("said, kind", [
    ("Stop listening.", "end"), ("That's all", "end"), ("Thanks Edith!", "end"), ("okay thank you", "end"),
    ("Bye Edith", "end"), ("never mind", "end"), ("Edith, stop", "end"),
    ("Yeah.", "ignore"), ("Hmm", "ignore"), ("okay", "ignore"), ("Lunch?", "ignore"), ("", "ignore"),
    ("Edith?", "wake"), ("Hey Edith.", "wake"),
    ("What's the time in London?", None), ("Let's get lunch at one", None), ("Edith what is Docker", None),
])
def test_followup_quick_kinds(said, kind):
    assert followup_kind(said) == kind


def _fu(c, msg):
    return c.post("/api/assistant", headers=auth(), json={"message": msg, "followup": True}).json()


def test_followup_side_conversation_ignored():
    c, p = _client(["NOT_FOR_ME"])
    r = _fu(c, "Let's get lunch at one after the call")
    assert r["kind"] == "ignore"
    assert len(p.calls) == 1 and "NOT_FOR_ME" in p.calls[0]  # no command guessing, one AI call


def test_followup_overheard_remark_never_becomes_ai_guessed_call():
    c, p = _client(["NOT_FOR_ME"])
    r = _fu(c, "we should ring up mom later today")
    assert r["kind"] == "ignore"
    assert len(p.calls) == 1 and "phone assistant" not in p.calls[0]  # never sent to the command classifier


def test_followup_question_answered():
    c, p = _client(["Docker packages apps into containers."])
    r = _fu(c, "And what is Docker used for?")
    assert r["kind"] == "answer" and r["reply"].startswith("Docker")


def test_followup_with_wake_word_is_always_for_edith():
    c, p = _client(["It's 9 PM in London."])
    r = _fu(c, "Edith, what's the time in London?")
    assert r["kind"] == "answer"
    assert "NOT_FOR_ME" not in p.calls[0] and "edith" not in p.calls[0].lower().split("london")[0]


def test_followup_command_and_end_and_filler_skip_ai():
    c, p = _client([])
    assert _fu(c, "Set a timer for 5 minutes")["action"] == {"type": "timer", "seconds": 300}
    assert _fu(c, "That's all, thanks")["kind"] == "end"
    assert _fu(c, "yeah")["kind"] == "ignore"
    assert _fu(c, "Edith")["reply"] == "Yes?"
    assert p.calls == []


def test_non_followup_unchanged():
    c, p = _client(["Answer."])
    r = c.post("/api/assistant", headers=auth(), json={"message": "Let's get lunch"}).json()
    assert r["kind"] == "answer" and "NOT_FOR_ME" not in p.calls[0]


# --- leads / email / whatsapp / song commands --------------------------------------

@pytest.mark.parametrize("said, expected", [
    ("Edith, find me leads for dentists in Indiranagar Bangalore", {"type": "find_leads", "query": "dentists in indiranagar bangalore"}),
    ("Find leads: gyms in Koramangala", {"type": "find_leads", "query": "gyms in koramangala"}),
    ("find me restaurants in Mysore without a website", {"type": "find_leads", "query": "restaurants in mysore"}),
    ("search for leads on google maps for salons in HSR layout", {"type": "find_leads", "query": "salons in hsr layout"}),
    ("Find me some leads", {"type": "find_leads", "query": ""}),
    ("Email Rahul saying the proposal is ready.", {"type": "email", "to": "Rahul", "message": "the proposal is ready."}),
    ("Send an email to priya@gmail.com about the meeting tomorrow at 10",
     {"type": "email", "to": "priya@gmail.com", "message": "about the meeting tomorrow at 10"}),
    ("email rahul at gmail dot com saying hello", {"type": "email", "to": "rahul@gmail.com", "message": "hello"}),
    ("Write a mail to my boss that I'll be late today", {"type": "email", "to": "my boss", "message": "I'll be late today"}),
    ("WhatsApp Rahul saying I'll be late by 10 minutes.", {"type": "whatsapp", "to": "Rahul", "message": "I'll be late by 10 minutes."}),
    ("Open WhatsApp and type hello how are you to Priya", {"type": "whatsapp", "to": "Priya", "message": "hello how are you"}),
    ("Send a WhatsApp message to Mom saying I reached home.", {"type": "whatsapp", "to": "Mom", "message": "I reached home."}),
    ("Message Arjun: are we meeting today?", {"type": "whatsapp", "to": "Arjun", "message": "are we meeting today?"}),
    ("Send Priya a message saying happy birthday!", {"type": "whatsapp", "to": "Priya", "message": "happy birthday!"}),
    ("Open Spotify and play Shape of You by Ed Sheeran",
     {"type": "play_music", "query": "shape of you by ed sheeran", "favorite": False, "app": "spotify",
      "title": "shape of you", "artist": "ed sheeran"}),
])
def test_new_commands(said, expected):
    assert parse_command(said) == expected


@pytest.mark.parametrize("said", ["How do I write an email to a client?", "What message should I send to the client?",
                                  "What are leads in sales?"])
def test_new_questions_not_commands(said):
    assert parse_command(said) is None


def test_validate_new_actions():
    assert validate_action({"type": "email", "to": "x", "message": ""}) is None
    assert validate_action({"type": "whatsapp", "to": "rahul", "message": "hi"}) == {"type": "whatsapp", "to": "rahul", "message": "hi"}
    assert validate_action({"type": "find_leads", "query": "cafes in goa"}) == {"type": "find_leads", "query": "cafes in goa"}
