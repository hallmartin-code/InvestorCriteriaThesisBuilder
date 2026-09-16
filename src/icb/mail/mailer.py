"""Send one result email through Resend (CLAUDE.md §16).

Stdlib HTTP, no SDK. Emailing is on only when RESEND_API_KEY and ICB_REPORT_EMAIL_TO are both
set; the recipient comes only from configuration, never from a request. A failure is recorded
and logged, never raised at the caller, because the artifacts are the product and the email is
a notification about them.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("icb.mail")

RESEND_ENDPOINT = "https://api.resend.com/emails"
TIMEOUT_S = 15
MAX_ATTEMPTS = 3
MIN_INTERVAL_S = 0.5  # Resend allows 2 requests per second
ATTACHMENT_BUDGET = 30 * 1024 * 1024
OMITTED_NOTE = "Attachments were omitted: they exceed the 30 MB email limit. The artifacts are in the app."

_last_send = 0.0


@dataclass
class EmailOutcome:
    status: str  # sent | skipped | not_configured | failed
    recipient: str = ""
    message_id: str | None = None
    reason: str | None = None
    dropped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "recipient": self.recipient, "reason": self.reason,
                "message_id": self.message_id, "dropped": self.dropped}


def recipients() -> list[str]:
    return [address.strip() for address in (os.getenv("ICB_REPORT_EMAIL_TO") or "").split(",") if address.strip()]


def sender() -> str:
    return (os.getenv("ICB_REPORT_EMAIL_FROM") or "").strip()


def configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY") and recipients() and sender())


def describe() -> dict[str, Any]:
    return {"enabled": configured(), "recipients": recipients(), "sender": sender()}


def idempotency_key(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _trim(attachments: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Drop the JSON first, then everything, rather than exceed the budget."""
    dropped: list[str] = []
    kept = list(attachments)
    while kept and sum(len(data) for _, data in kept) * 4 // 3 > ATTACHMENT_BUDGET:
        name, _ = kept.pop()  # callers pass the PDF first, so the JSON goes first
        dropped.append(name)
    return kept, dropped


def send(
    *,
    subject: str,
    html: str,
    text: str,
    attachments: list[tuple[str, bytes]] | None = None,
    key: str | None = None,
) -> EmailOutcome:
    global _last_send
    if not configured():
        return EmailOutcome(status="not_configured", reason="Result emails are not configured on this server.")

    to = recipients()
    kept, dropped = _trim(list(attachments or []))
    if dropped:
        html += f"<p>{OMITTED_NOTE}</p>"
        text += f"\n\n{OMITTED_NOTE}"

    payload: dict[str, Any] = {
        "from": sender(), "to": to, "subject": subject, "html": html, "text": text,
        "attachments": [{"filename": name, "content": base64.b64encode(data).decode("ascii")} for name, data in kept],
    }
    headers = {
        "Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}",
        "Content-Type": "application/json",
    }
    if key:
        headers["Idempotency-Key"] = key

    delay = 1.0
    reason = "The email could not be sent."
    for attempt in range(1, MAX_ATTEMPTS + 1):
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_send)
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(RESEND_ENDPOINT, data=json.dumps(payload).encode("utf-8"),
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - fixed https URL
                _last_send = time.monotonic()
                body = json.loads(response.read().decode("utf-8") or "{}")
            message_id = body.get("id")
            log.info("Result email sent to %s (id %s)", ", ".join(a.split("@")[-1] for a in to), message_id)
            return EmailOutcome(status="sent", recipient=", ".join(to), message_id=message_id, dropped=dropped)
        except urllib.error.HTTPError as exc:
            _last_send = time.monotonic()
            reason = _readable(exc)
            if exc.code not in (429, 500, 502, 503, 504) or attempt == MAX_ATTEMPTS:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _last_send = time.monotonic()
            reason = f"Resend could not be reached ({exc.__class__.__name__})."
            if attempt == MAX_ATTEMPTS:
                break
        time.sleep(delay)
        delay *= 2

    log.warning("Result email to %s failed: %s", ", ".join(a.split("@")[-1] for a in to), reason)
    return EmailOutcome(status="failed", recipient=", ".join(to), reason=reason, dropped=dropped)


def _readable(exc: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(exc.read().decode("utf-8") or "{}").get("message")
    except (ValueError, OSError):
        detail = None
    if exc.code in (401, 403):
        return "Resend rejected the API key."
    if exc.code == 422 and detail:
        return f"Resend rejected the message: {detail}"
    return f"Resend returned {exc.code}." + (f" {detail}" if detail else "")
