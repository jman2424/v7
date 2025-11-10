"""
Email connector.

Supports two backends:
- SMTP (standard): SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
- HTTP API (Mailgun/Sendgrid-like): MAIL_API_URL, MAIL_API_KEY, MAIL_FROM

Usage:
    mail = Emailer.from_env()
    mail.send("to@example.com", subject="Alert", text="Body")
"""

from __future__ import annotations
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional, Dict, Any

import json
import urllib.request


@dataclass
class Emailer:
    # Chosen backend
    backend: str  # "smtp" | "http"

    # SMTP config
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: bool = True

    # HTTP API config
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    api_from: Optional[str] = None

    @classmethod
    def from_env(cls, *, force_smtp: bool | None = None) -> "Emailer":
        # Prefer HTTP if set and not forced to SMTP
        api_url = os.getenv("MAIL_API_URL")
        api_key = os.getenv("MAIL_API_KEY")
        api_from = os.getenv("MAIL_FROM") or os.getenv("SMTP_FROM")

        if api_url and api_key and not force_smtp:
            return cls(
                backend="http",
                api_url=api_url,
                api_key=api_key,
                api_from=api_from or "no-reply@example.com",
            )

        # Else SMTP
        return cls(
            backend="smtp",
            smtp_host=os.getenv("SMTP_HOST"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER"),
            smtp_pass=os.getenv("SMTP_PASS"),
            smtp_from=os.getenv("SMTP_FROM") or "no-reply@example.com",
            smtp_tls=os.getenv("SMTP_TLS", "1") not in {"0", "false", "off"},
        )

    # -------- public API --------

    def send(self, to: str, *, subject: str, text: str = "", html: Optional[str] = None) -> bool:
        if self.backend == "http":
            return self._send_http(to=to, subject=subject, text=text, html=html)
        return self._send_smtp(to=to, subject=subject, text=text, html=html)

    def send_owner_alert(self, owner_email: str, *, title: str, body: str) -> bool:
        subject = f"[ASA Alert] {title}"
        return self.send(owner_email, subject=subject, text=body)

    def send_daily_summary(self, owner_email: str, *, tenant: str, kpis: Dict[str, Any]) -> bool:
        subject = f"[ASA Summary] {tenant}"
        text = json.dumps(kpis, indent=2)
        return self.send(owner_email, subject=subject, text=text)

    # -------- backends --------

    def _send_smtp(self, to: str, *, subject: str, text: str, html: Optional[str]) -> bool:
        if not self.smtp_host:
            raise RuntimeError("SMTP_HOST not configured")
        msg = EmailMessage()
        msg["From"] = self.smtp_from or "no-reply@example.com"
        msg["To"] = to
        msg["Subject"] = subject
        if html:
            msg.set_content(text or "")
            msg.add_alternative(html, subtype="html")
        else:
            msg.set_content(text or "")

        context = ssl.create_default_context()
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
            server.ehlo()
            if self.smtp_tls:
                server.starttls(context=context)
                server.ehlo()
            if self.smtp_user and self.smtp_pass:
                server.login(self.smtp_user, self.smtp_pass)
            server.send_message(msg)
        return True

    def _send_http(self, to: str, *, subject: str, text: str, html: Optional[str]) -> bool:
        if not self.api_url or not self.api_key:
            raise RuntimeError("MAIL_API_URL/MAIL_API_KEY not configured")
        payload = {
            "from": self.api_from or "no-reply@example.com",
            "to": to,
            "subject": subject,
            "text": text or "",
        }
        if html:
            payload["html"] = html

        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                return True
            raise RuntimeError(f"Mail API returned {resp.status}")
