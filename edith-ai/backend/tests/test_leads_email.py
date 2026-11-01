"""Lead finder (Google Places mocked) and Gmail sending (SMTP mocked)."""
import smtplib

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.leads_service import SEARCH_URL, is_social_only
from tests.conftest import BOB, auth, make_settings


def place(i, website=None, phone="080 1234 567", status="OPERATIONAL"):
    p = {"id": f"p{i}", "displayName": {"text": f"Biz {i}"}, "formattedAddress": f"{i} MG Road",
         "rating": 4.5, "userRatingCount": 10 + i, "businessStatus": status,
         "googleMapsUri": f"https://maps.google.com/?cid={i}"}
    if phone:
        p["nationalPhoneNumber"] = phone
        p["internationalPhoneNumber"] = "+91 " + phone
    if website:
        p["websiteUri"] = website
    return p


def client(**kw):
    return TestClient(create_app(make_settings(google_maps_api_key="maps-key", **kw)))


@respx.mock
def test_leads_without_website_only():
    route = respx.post(SEARCH_URL).mock(return_value=httpx.Response(200, json={"places": [
        place(1),                                            # no website -> lead
        place(2, website="https://biz2.com"),               # real website -> skip
        place(3, website="https://www.facebook.com/biz3"),  # social only -> lead
        place(4, phone=None),                                # no phone -> skip
        place(5, status="CLOSED_PERMANENTLY"),               # closed -> skip
    ]}))
    r = client().post("/api/leads/search", headers=auth(), json={"query": "dentists in Indiranagar"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [l["name"] for l in body["leads"]] == ["Biz 1", "Biz 3"]
    assert body["leads"][1]["social_url"] == "https://www.facebook.com/biz3"
    assert body["scanned"] == 5
    req = route.calls[0].request
    assert req.headers["X-Goog-Api-Key"] == "maps-key"
    assert "places.websiteUri" in req.headers["X-Goog-FieldMask"]


@respx.mock
def test_leads_paginates_until_enough():
    pages = [httpx.Response(200, json={"places": [place(i) for i in range(20)], "nextPageToken": "t2"}),
             httpx.Response(200, json={"places": [place(i) for i in range(20, 30)]})]
    route = respx.post(SEARCH_URL).mock(side_effect=pages)
    r = client().post("/api/leads/search", headers=auth(), json={"query": "cafes in goa", "max_leads": 25})
    assert len(r.json()["leads"]) == 25
    assert route.call_count == 2
    assert b'"pageToken": "t2"' in route.calls[1].request.content or b'"pageToken":"t2"' in route.calls[1].request.content


@respx.mock
def test_leads_bad_key_message():
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(403, json={"error": {
        "message": "API key not valid", "status": "PERMISSION_DENIED"}}))
    r = client().post("/api/leads/search", headers=auth(), json={"query": "gyms"})
    assert r.status_code == 502 and "Places API (New)" in r.json()["error"]["message"]
    assert "maps-key" not in r.text


def test_leads_not_configured():
    c = TestClient(create_app(make_settings()))
    r = c.post("/api/leads/search", headers=auth(), json={"query": "gyms"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "leads_not_configured"
    assert c.get("/health").json()["leads_configured"] is False


def test_save_list_export_delete_leads_and_ownership():
    c = client()
    lead = {"place_id": "p1", "name": "=HYPERLINK(evil)", "phone": "080 1", "address": "MG Road"}
    saved = c.post("/api/leads", headers=auth(), json=lead).json()
    c.post("/api/leads", headers=auth(), json={**lead, "status": "called"})  # same business: updated, not duplicated
    rows = c.get("/api/leads", headers=auth()).json()
    assert len(rows) == 1 and rows[0]["status"] == "called"
    assert c.get("/api/leads", headers=auth(BOB)).json() == []
    csv_text = c.get("/api/leads/export.csv", headers=auth()).text
    assert "'=HYPERLINK(evil)" in csv_text  # spreadsheet formula neutralised
    assert c.delete(f"/api/leads/{saved['id']}", headers=auth(BOB)).status_code == 404
    assert c.delete(f"/api/leads/{saved['id']}", headers=auth()).status_code == 204


def test_social_detection():
    assert is_social_only("https://instagram.com/x") and is_social_only("wa.me/9198")
    assert not is_social_only("https://smiledental.in") and not is_social_only(None)


# --- email -------------------------------------------------------------------------

class FakeSMTP:
    sent = []
    fail_auth = False

    def __init__(self, host, port, timeout=None, context=None):
        assert (host, port) == ("smtp.gmail.com", 465)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        if FakeSMTP.fail_auth:
            raise smtplib.SMTPAuthenticationError(535, b"bad")
        assert pw == "abcdefghijklmnop"  # spaces from Google's display removed

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def email_client(monkeypatch, replies=None):
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail_auth = [], False
    app = create_app(make_settings(gmail_address="me@gmail.com", gmail_app_password="abcd efgh ijkl mnop",
                                   email_sender_name="Harsha"))
    if replies is not None:
        from tests.test_commands import ScriptedProvider
        app.state.ai._provider = ScriptedProvider(replies)
    return TestClient(app)


def test_email_draft_and_send(monkeypatch):
    c = email_client(monkeypatch, ['{"subject": "Proposal ready", "body": "Hi Rahul,\\n\\nThe proposal is ready.\\n\\nBest,\\nHarsha"}'])
    d = c.post("/api/email/draft", headers=auth(), json={"to_name": "Rahul", "instruction": "the proposal is ready"}).json()
    assert d["subject"] == "Proposal ready" and "Harsha" in d["body"]
    r = c.post("/api/email/send", headers=auth(), json={"to": "rahul@example.com", **d, "confirmed": True})
    assert r.json() == {"sent": True}
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "rahul@example.com" and msg["Subject"] == "Proposal ready"
    assert "Harsha" in msg["From"] and "me@gmail.com" in msg["From"]


def test_email_requires_confirmation_and_valid_address(monkeypatch):
    c = email_client(monkeypatch)
    body = {"to": "rahul@example.com", "subject": "x", "body": "y", "confirmed": False}
    assert c.post("/api/email/send", headers=auth(), json=body).json()["error"]["code"] == "confirmation_required"
    bad = c.post("/api/email/send", headers=auth(), json={**body, "to": "not-an-email", "confirmed": True})
    assert bad.json()["error"]["code"] == "invalid_email"
    assert FakeSMTP.sent == []


def test_email_header_injection_blocked(monkeypatch):
    c = email_client(monkeypatch)
    c.post("/api/email/send", headers=auth(), json={"to": "a@b.com", "subject": "Hi\nBcc: victim@x.com",
                                                    "body": "y", "confirmed": True})
    assert "\n" not in FakeSMTP.sent[0]["Subject"] and FakeSMTP.sent[0]["Bcc"] is None


def test_email_bad_app_password(monkeypatch):
    c = email_client(monkeypatch)
    FakeSMTP.fail_auth = True
    r = c.post("/api/email/send", headers=auth(), json={"to": "a@b.com", "subject": "x", "body": "y", "confirmed": True})
    assert r.status_code == 502 and r.json()["error"]["code"] == "email_auth"


def test_email_not_configured():
    c = TestClient(create_app(make_settings()))
    r = c.post("/api/email/draft", headers=auth(), json={"instruction": "hi"})
    assert r.json()["error"]["code"] == "email_not_configured"
    assert c.get("/health").json()["email_configured"] is False
