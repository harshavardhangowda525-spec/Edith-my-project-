"""Send-only Gmail via SMTP + App password. EDITH never reads the inbox.

The phone app always reads the draft back and asks "Send it?" before calling /api/email/send.
"""
from __future__ import annotations

import json
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.errors import ConfigurationError, ProviderError, ValidationFailed
from app.services.ai_service import AIService

log = logging.getLogger("edith.email")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

DRAFT_PROMPT = """Write a short, professional email for the user.
Recipient: {to_name}
What the user said the email should say: "{instruction}"
Sender name for the sign-off: {sender}

Rules: keep the user's meaning, do not invent facts, dates, prices or promises, plain text, 2-6
short sentences, friendly and professional. Reply with ONLY a JSON object:
{{"subject": "<short subject>", "body": "<email body including greeting and sign-off>"}}"""


def check_address(address: str) -> str:
    address = address.strip()
    if not EMAIL_RE.match(address) or len(address) > 254:
        raise ValidationFailed(f"'{address}' is not a valid email address", code="invalid_email")
    return address


class EmailService:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def _require(self) -> None:
        if not self.s.email_configured:
            raise ConfigurationError("Email is not set up: add GMAIL_ADDRESS and GMAIL_APP_PASSWORD on the "
                                     "server (see docs/LEADS_AND_EMAIL.md).", code="email_not_configured")

    async def draft(self, ai: AIService, to_name: str, instruction: str) -> dict[str, str]:
        self._require()
        sender = self.s.email_sender_name or (self.s.gmail_address or "").split("@")[0]
        result = await ai.chat(DRAFT_PROMPT.format(to_name=to_name or "the recipient",
                                                   instruction=instruction.replace('"', "'"),
                                                   sender=sender), [], mode="detailed")
        m = re.search(r"\{.*\}", result.text, re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
        except ValueError:
            data = {}
        subject = str(data.get("subject") or "").strip()[:150]
        body = str(data.get("body") or "").strip()[:8000]
        if not body:  # model ignored the format: use its text as the body
            body = result.text.strip()[:8000]
        if not subject:
            subject = (instruction.strip().split(".")[0] or "Message")[:80]
        return {"subject": subject, "body": body}

    async def send(self, to: str, subject: str, body: str) -> None:
        self._require()
        to = check_address(to)
        msg = EmailMessage()
        sender_name = self.s.email_sender_name or ""
        msg["From"] = formataddr((sender_name, self.s.gmail_address or "")) if sender_name else self.s.gmail_address
        msg["To"] = to
        msg["Subject"] = " ".join(subject.split())[:150]  # no header injection via newlines
        msg.set_content(body[:10000])
        await run_in_threadpool(self._smtp_send, msg)
        log.info("email sent to *@%s", to.split("@")[1])

    def _smtp_send(self, msg: EmailMessage) -> None:
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20, context=ssl.create_default_context()) as smtp:
                smtp.login(self.s.gmail_address or "", self.s.gmail_app_password or "")
                smtp.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            raise ProviderError("Gmail rejected the login. Check GMAIL_ADDRESS and the App password.",
                                code="email_auth") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise ProviderError(f"Could not send the email ({type(exc).__name__}).", code="email_error") from exc
