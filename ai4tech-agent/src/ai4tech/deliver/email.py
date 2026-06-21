"""SMTP email deliverer — selectable alternative target (FR-DEL-1).

Secrets (SMTP username/password) come from the environment, never config.
"""

from __future__ import annotations

import os

from ..models import Brief
from .base import render_markdown


class EmailDeliverer:
    def __init__(self, email_cfg: dict) -> None:
        self.cfg = email_cfg

    def deliver(self, brief: Brief) -> str:  # pragma: no cover - network
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = f"AI4Tech Intelligence Brief — {brief.run_id}"
        msg["From"] = self.cfg.get("from_addr", "ai4tech-agent@example.com")
        msg["To"] = self.cfg.get("to_addr", "lead@example.com")
        msg.set_content(render_markdown(brief))

        host = self.cfg.get("smtp_host", "localhost")
        port = int(self.cfg.get("smtp_port", 587))
        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls()
            user = os.environ.get("SMTP_USERNAME")
            password = os.environ.get("SMTP_PASSWORD")
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return f"email to {msg['To']}"
