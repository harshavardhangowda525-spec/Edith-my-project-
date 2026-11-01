"""Turns a spoken sentence into a phone action (call, open app, play music, ...) or a question.

Order of work:
1. Fast, deterministic patterns for the common phrasings ("call mom", "open spotify and play
   my favourite music", "set an alarm for 6 am", "pause", ...).
2. If the sentence still looks like a command, ask the AI to fill a strict JSON schema.
3. Otherwise it is a normal question and the caller answers it with chat.

Actions are only *descriptions*; the phone app executes them on the device, with its own
permissions and confirmations. Contact lists never reach the server: the phone resolves names.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.ai_service import AIService

log = logging.getLogger("edith.commands")

MUSIC_APPS = {
    "spotify": "spotify",
    "youtube music": "youtube_music",
    "yt music": "youtube_music",
    "youtube": "youtube",
    "jiosaavn": "jiosaavn",
    "jio saavn": "jiosaavn",
    "saavn": "jiosaavn",
    "gaana": "gaana",
    "wynk": "wynk",
    "amazon music": "amazon_music",
    "apple music": "apple_music",
}
MEDIA_COMMANDS = {"pause", "play", "resume", "next", "previous", "stop", "volume_up", "volume_down", "mute"}
FAVOURITE_WORDS = re.compile(
    r"^(?:(?:my|some|the)\s+)?(?:favou?rite|liked|usual|own)?\s*(?:music|songs?|playlist|tracks?|mix)?$"
)
NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90, "half an": 0.5,
}
COMMAND_HINTS = re.compile(
    r"\b(call|phone|ring|dial|open|launch|start|play|pause|stop|resume|skip|next|previous|volume|"
    r"louder|quieter|mute|alarm|wake me|timer|navigate|directions|take me|drive me|music|song|"
    r"leads?|prospects?|e-?mail|mail|whatsapp|message|text)\b"
)
_LEADING = re.compile(
    r"^(?:(?:hey|ok|okay)\s+)?(?:edith[\s,]+)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
    r"(?:(?:just|quickly)\s+)?"
)


def normalise(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"[“”\"!?]", "", t)
    t = re.sub(r"[.,;:]+(\s|$)", r" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = _LEADING.sub("", t)
    t = re.sub(r"\s+(?:please|for me|now|right now)$", "", t)
    return t.strip()


def _number(word: str) -> float | None:
    word = word.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", word):
        return float(word)
    return NUMBER_WORDS.get(word)


def _music_app(text: str) -> tuple[str, str | None]:
    """Strip a trailing 'on spotify' / 'in youtube music' and return (rest, app)."""
    for name, key in sorted(MUSIC_APPS.items(), key=lambda kv: -len(kv[0])):
        m = re.search(rf"\s+(?:on|in|using|from|with)\s+{re.escape(name)}(?:\s+app)?$", text)
        if m:
            return text[: m.start()].strip(), key
    return text, None


def _play(query: str, app: str | None) -> dict[str, Any]:
    query = re.sub(r"^(?:the\s+)?(?:song|track)\s+", "", query.strip())
    favourite = not query or bool(FAVOURITE_WORDS.match(query))
    action: dict[str, Any] = {"type": "play_music", "query": "" if favourite else query,
                              "favorite": favourite, "app": app}
    m = re.match(r"^(.+?)\s+by\s+(.+)$", query) if not favourite else None
    if m:  # "shape of you by ed sheeran" -> exact track hint for the music app
        action["title"], action["artist"] = m.group(1).strip(), m.group(2).strip()
    return action


_RAW_LEADING = re.compile(
    r"^\W*(?:(?:hey|ok|okay)\s+)?(?:edith[\s,.:!-]+)?(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?",
    re.I)
_SAY = r"(?:saying|that says|which says|telling (?:him|her|them)|to say|and say|that|:|-)"


def parse_message(text: str) -> dict[str, Any] | None:
    """WhatsApp messages and emails. Uses the original casing so the message reads naturally."""
    raw = _RAW_LEADING.sub("", text.strip()).strip()
    raw = re.sub(r"\s+(?:please)\.?$", "", raw, flags=re.I)
    patterns = [
        # email
        ("email", rf"^(?:send|write)?\s*(?:an?\s+)?(?:e-?mail|mail)\s+(?:to\s+)?(?P<to>[^:]+?)\s*(?:{_SAY}|(?=about\s|regarding\s))\s*(?P<msg>.+)$"),
        ("email", rf"^(?:send|write)\s+(?P<to>.+?)\s+an?\s+(?:e-?mail|mail)\s*{_SAY}?\s*(?P<msg>.+)$"),
        # whatsapp
        ("whatsapp", r"^open\s+whatsapp\s+and\s+(?:type|send|write|say|text)\s+(?P<msg>.+?)\s+to\s+(?P<to>[^,]+?)\.?$"),
        ("whatsapp", rf"^(?:open\s+whatsapp\s+and\s+)?(?:send|write|type)?\s*(?:an?\s+)?(?:whatsapp|message|text|msg)"
                     rf"(?:\s+message)?\s+(?:to\s+)?(?P<to>[^:]+?)(?:\s+on\s+whatsapp)?\s*{_SAY}\s*(?P<msg>.+)$"),
        ("whatsapp", rf"^(?:send|write)\s+(?P<to>.+?)\s+an?\s+(?:whatsapp|message|text)(?:\s+message)?(?:\s+on\s+whatsapp)?"
                     rf"\s*{_SAY}?\s*(?P<msg>.+)$"),
        ("whatsapp", rf"^(?:on\s+)?whatsapp\s+(?P<to>[^:]+?)\s*{_SAY}\s*(?P<msg>.+)$"),
    ]
    for kind, pat in patterns:
        m = re.match(pat, raw, re.I)
        if not m:
            continue
        to = m.group("to").strip(" ,.")
        msg = m.group("msg").strip()
        to = re.sub(r"\s+on\s+whatsapp$", "", to, flags=re.I)
        if kind == "email":
            # "rahul at gmail dot com" -> rahul@gmail.com
            to = re.sub(r"\s+at\s+", "@", to, flags=re.I) if re.search(r"\sdot\s", to, re.I) else to
            to = re.sub(r"\s+dot\s+", ".", to, flags=re.I)
        if to and msg and len(to.split()) <= 5:
            return {"type": kind, "to": to, "message": msg}
    return None


def parse_leads(t: str) -> dict[str, Any] | None:
    m = re.match(r"^(?:find|get|search(?: for)?|look for|show)(?: me)?(?: some| new| a few)?\s+"
                 r"(?:leads?|clients?|prospects?|customers?)(?:\s+(?:for|of|in|near|on|among|from))?\s*(.*)$", t) or \
        re.match(r"^(?:find|get|search(?: for)?|look for|show)(?: me)?\s+(.+?)\s+"
                 r"(?:without|with no|that don'?t have|who don'?t have|having no)\s+(?:a\s+)?websites?(.*)$", t)
    if not m:
        return None
    query = " ".join(g for g in m.groups() if g).strip()
    query = re.sub(r"\s*(?:without|with no|that don'?t have|who don'?t have|having no)\s+(?:a\s+)?websites?\s*", " ", query)
    query = re.sub(r"^(?:(?:on|from|using|through)\s+)?google maps\s*(?:(?:for|in|of)\s+)?", "", query)
    query = re.sub(r"\s+(?:on|from|using|through)\s+google maps$", "", query)
    return {"type": "find_leads", "query": " ".join(query.split())}


def parse_command(text: str) -> dict[str, Any] | None:
    """Return an action dict for common phrasings, or None."""
    msg = parse_message(text)
    if msg:
        return msg
    t = normalise(text)
    if not t:
        return None
    leads = parse_leads(t)
    if leads:
        return leads

    # --- music: "open spotify and play my favourite music", "play arijit singh on spotify"
    m = re.match(r"^(?:open|launch|start|go to)\s+(?:the\s+)?(.+?)(?:\s+app)?\s+and\s+(?:then\s+)?(?:play|put on)\s*(.*)$", t)
    if m:
        app_words, rest = m.group(1).strip(), m.group(2).strip()
        rest, app2 = _music_app(rest)
        return _play(rest, app2 or MUSIC_APPS.get(app_words))
    m = re.match(r"^(?:play|put on|start playing|listen to)(?:\s+(.*))?$", t)
    if m:
        rest, app = _music_app(m.group(1) or "")
        if rest in {"", "it", "again"} and app is None:
            return {"type": "media", "command": "play"}
        return _play(rest, app)

    # --- media keys
    media = {
        r"(?:pause|hold)(?:\s+(?:the\s+)?(?:music|song|track|it))?": "pause",
        r"(?:stop)(?:\s+(?:the\s+)?(?:music|song|playing|track))?": "stop",
        r"(?:resume|continue|unpause)(?:\s+(?:the\s+)?(?:music|song|playing|track))?": "resume",
        r"(?:next|skip)(?:\s+(?:this\s+|the\s+)?(?:song|track|one))?|(?:play\s+)?(?:the\s+)?next\s+(?:song|track)": "next",
        r"(?:previous|go back|last)(?:\s+(?:song|track))?|(?:play\s+)?(?:the\s+)?previous\s+(?:song|track)": "previous",
        r"(?:volume up|turn (?:it|the volume|the music)? ?up|louder|increase (?:the )?volume|raise (?:the )?volume)": "volume_up",
        r"(?:volume down|turn (?:it|the volume|the music)? ?down|quieter|softer|lower (?:the )?volume|decrease (?:the )?volume|reduce (?:the )?volume)": "volume_down",
        r"(?:mute|silence)(?:\s+(?:the\s+)?(?:music|sound|volume))?": "mute",
    }
    for pattern, cmd in media.items():
        if re.fullmatch(pattern, t):
            return {"type": "media", "command": cmd}

    # --- calls: "call mom", "call rahul on his mobile", "make a call to dad", "phone my wife"
    m = re.match(r"^(?:call|phone|ring|dial|make a (?:phone )?call to|give a call to|give)\s+(.+?)(?:\s+a\s+(?:call|ring))?$", t)
    if m:
        who = re.sub(r"\s+(?:on|at)\s+(?:his|her|their|the)?\s*(?:mobile|phone|cell|number|work|home)$", "", m.group(1))
        who = re.sub(r"^(?:to\s+)", "", who).strip()
        if who and who not in {"me", "back"}:
            return {"type": "call", "contact": who}

    # --- alarm: "set an alarm for 6 am", "wake me up at 6:30", "alarm at 7"
    m = re.match(
        r"^(?:set\s+)?(?:an?\s+|my\s+)?(?:alarm|wake me up|wake me)\s*(?:for|at)?\s*"
        r"(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?|in the morning|in the evening|at night|tonight)?"
        r"(?:\s+(?:tomorrow|today))?(?:\s+(?:called|named|for)\s+(.+))?$", t)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        ampm = (m.group(3) or "").replace(".", "").replace(" ", "")
        if ampm in {"pm", "intheevening", "atnight", "tonight"} and hour < 12:
            hour += 12
        if ampm in {"am", "inthemorning"} and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return {"type": "alarm", "hour": hour, "minute": minute, "label": (m.group(4) or "").strip() or None}

    # --- timer: "set a timer for 10 minutes", "10 minute timer", "timer 30 seconds"
    m = re.match(r"^(?:set\s+)?(?:a\s+)?timer\s+(?:for\s+)?(.+?)\s+(seconds?|secs?|minutes?|mins?|hours?|hrs?)$", t) or \
        re.match(r"^(?:set\s+)?(?:a\s+)?(.+?)[\s-](second|sec|minute|min|hour|hr)s?\s+timer$", t)
    if m:
        n = _number(m.group(1))
        unit = m.group(2)
        if n:
            secs = int(n * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1))
            if 0 < secs <= 24 * 3600:
                return {"type": "timer", "seconds": secs}

    # --- navigation: "navigate to the airport", "take me home", "directions to mg road"
    m = re.match(r"^(?:navigate|directions|get directions|take me|drive me|drive|show me the way|how do i get)\s+(?:to\s+)?(?:the\s+)?(.+)$", t)
    if m and not m.group(1).startswith(("what", "how")):
        return {"type": "navigate", "destination": m.group(1).strip()}

    # --- open app: "open instagram", "launch the camera app"
    m = re.match(r"^(?:open|launch|start|go to)\s+(?:the\s+|my\s+)?(.+?)(?:\s+app(?:lication)?)?$", t)
    if m and len(m.group(1).split()) <= 4:
        return {"type": "open_app", "app": m.group(1).strip()}

    return None


CLASSIFY_PROMPT = """The user spoke this to their phone assistant: "{text}"

If it is a request to control the phone, reply with ONLY one JSON object, no other text:
{{"type":"call","contact":"<name as spoken>"}}
{{"type":"open_app","app":"<app name>"}}
{{"type":"play_music","query":"<song/artist/playlist, empty for their favourite music>","favorite":<true|false>,"app":"<spotify|youtube_music|youtube|jiosaavn|gaana|wynk|amazon_music|apple_music|null>"}}
{{"type":"media","command":"<pause|play|resume|next|previous|stop|volume_up|volume_down|mute>"}}
{{"type":"alarm","hour":<0-23>,"minute":<0-59>,"label":null}}
{{"type":"timer","seconds":<number>}}
{{"type":"navigate","destination":"<place>"}}
{{"type":"find_leads","query":"<business type and area, e.g. dentists in Indiranagar Bangalore>"}}
{{"type":"email","to":"<contact name or email address>","message":"<what the email should say>"}}
{{"type":"whatsapp","to":"<contact name>","message":"<exact message text>"}}
If it is NOT a phone command (a question, a chat, anything else) reply with exactly: {{"type":"none"}}"""

_ALLOWED_TYPES = {"call", "open_app", "play_music", "media", "alarm", "timer", "navigate",
                  "find_leads", "email", "whatsapp"}


def validate_action(a: Any) -> dict[str, Any] | None:
    """Keep only well-formed actions with safe, bounded values."""
    if not isinstance(a, dict) or a.get("type") not in _ALLOWED_TYPES:
        return None
    t = a["type"]

    def s(key: str, limit: int = 100) -> str:
        v = a.get(key)
        return str(v).strip()[:limit] if v is not None else ""

    if t == "call":
        return {"type": t, "contact": s("contact")} if s("contact") else None
    if t == "open_app":
        return {"type": t, "app": s("app")} if s("app") else None
    if t == "play_music":
        app = a.get("app")
        app = app if app in set(MUSIC_APPS.values()) else None
        q = s("query", 200)
        fav = bool(a.get("favorite")) or not q
        out = {"type": t, "query": "" if fav else q, "favorite": fav, "app": app}
        if not fav and s("title") and s("artist"):
            out["title"], out["artist"] = s("title", 200), s("artist", 200)
        return out
    if t == "find_leads":
        return {"type": t, "query": s("query", 200)}
    if t in ("email", "whatsapp"):
        to, msg = s("to", 200), s("message", 2000 if t == "email" else 1000)
        return {"type": t, "to": to, "message": msg} if to and msg else None
    if t == "media":
        c = s("command")
        return {"type": t, "command": c} if c in MEDIA_COMMANDS else None
    if t == "alarm":
        try:
            h, mi = int(a.get("hour")), int(a.get("minute", 0))
        except (TypeError, ValueError):
            return None
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return {"type": t, "hour": h, "minute": mi, "label": s("label") or None}
        return None
    if t == "timer":
        try:
            secs = int(float(a.get("seconds")))
        except (TypeError, ValueError):
            return None
        return {"type": t, "seconds": secs} if 0 < secs <= 24 * 3600 else None
    if t == "navigate":
        return {"type": t, "destination": s("destination", 200)} if s("destination") else None
    return None


def _extract_json(text: str) -> Any:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


async def understand(text: str, ai: AIService, allow_ai: bool = True) -> dict[str, Any] | None:
    """Return a validated action, or None when the sentence is a normal question.

    allow_ai=False (sentences overheard in conversation mode without "Edith") only accepts the exact
    command patterns, so a remark like "let's call mom later" is never turned into an action by guessing.
    """
    action = parse_command(text)
    if action:
        return validate_action(action)
    if not allow_ai or not COMMAND_HINTS.search(normalise(text)):
        return None
    result = await ai.chat(CLASSIFY_PROMPT.format(text=text.replace('"', "'")[:500]), [], mode="detailed")
    if result.mock:
        return None
    return validate_action(_extract_json(result.text))


def describe(action: dict[str, Any]) -> str:
    """Short sentence the phone can speak before doing the action."""
    t = action["type"]
    if t == "call":
        return f"Calling {action['contact']}."
    if t == "open_app":
        return f"Opening {action['app']}."
    if t == "play_music":
        what = "your favourite music" if action.get("favorite") else action.get("query")
        return f"Playing {what}."
    if t == "media":
        return {"pause": "Paused.", "stop": "Stopped.", "next": "Next song.", "previous": "Previous song.",
                "volume_up": "Volume up.", "volume_down": "Volume down.", "mute": "Muted."}.get(action["command"], "Okay.")
    if t == "alarm":
        h, m = action["hour"], action["minute"]
        suffix = "AM" if h < 12 else "PM"
        return f"Alarm set for {(h % 12) or 12}:{m:02d} {suffix}."
    if t == "timer":
        s = action["seconds"]
        return f"Timer set for {s // 60} minutes." if s >= 60 and s % 60 == 0 else f"Timer set for {s} seconds."
    if t == "navigate":
        return f"Starting directions to {action['destination']}."
    if t == "find_leads":
        q = action.get("query")
        return f"Looking for {q} without a website." if q else "Which businesses, and where? For example, dentists in Indiranagar."
    if t == "email":
        return f"Writing an email to {action['to']}."
    if t == "whatsapp":
        return f"WhatsApp to {action['to']}: {action['message']}"
    return "Okay."


# --- Conversation mode -------------------------------------------------------------------

_END_PHRASES = re.compile(
    r"^(?:(?:ok(?:ay)?|alright|thanks|thank you)\s+)?(?:edith\s+)?(?:"
    r"stop(?: listening)?|that'?s all|that is all|that'?s it|thanks(?: edith)?|thank you(?: edith)?|"
    r"bye(?: edith)?|goodbye(?: edith)?|go to sleep|sleep|never ?mind|nothing|no thanks|we'?re done|i'?m done|"
    r"you can stop|stop now|enough)(?:\s+edith)?(?:\s+(?:thanks|thank you)(?:\s+edith)?)?$"
)
_FILLER = re.compile(r"^(?:ok(?:ay)?|yeah|yes|no|hmm+|uh+|um+|right|sure|cool|nice|great|wow|oh|ah|haha|lol|mm+|huh)$")
WAKE = re.compile(r"\b(?:hey\s+)?edith\b[\s,.!?]*", re.I)


def addressed_to_edith(text: str) -> bool:
    return bool(WAKE.search(text))


def strip_wake_word(text: str) -> str:
    return WAKE.sub(" ", text).strip(" ,.!?") .strip()


def followup_kind(text: str) -> str | None:
    """Cheap decisions for conversation mode: 'end', 'ignore', 'wake' (said just 'Edith'), or None."""
    t = re.sub(r"[.,!?]", "", text.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return "ignore"
    if _END_PHRASES.match(t):
        return "end"
    if addressed_to_edith(text) and not strip_wake_word(text):
        return "wake"
    if not addressed_to_edith(text) and (_FILLER.match(t) or len(t.split()) == 1):
        return "ignore"
    return None


NOT_FOR_ME = "NOT_FOR_ME"
FOLLOWUP_NOTE = (
    "\n\n(Heard in conversation mode: the user may also be talking to other people nearby. "
    "If this sentence is clearly NOT addressed to you - side conversation with someone else, talking "
    "on the phone, background speech, reading aloud, or filler - reply with exactly " + NOT_FOR_ME + ". "
    "If it is a question, request, task or follow-up for you, answer normally.)"
)
