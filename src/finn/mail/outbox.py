"""Antwort-Mail aufbauen (Thread-Header) und per SMTP versenden."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


@dataclass
class Antwort:
    an: str
    betreff: str
    in_reply_to: str
    references: str
    html: str
    text: str
    ist_fehler: bool = False


def baue_email(a: Antwort, absender: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = absender
    m["To"] = a.an
    m["Subject"] = a.betreff
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=absender.rpartition("@")[2] or None)
    if a.in_reply_to:
        m["In-Reply-To"] = a.in_reply_to
        m["References"] = a.references
    m.set_content(a.text)
    m.add_alternative(a.html, subtype="html")
    return m


def sende(cfg, a: Antwort) -> EmailMessage:
    m = baue_email(a, cfg.mail_user)
    if cfg.smtp_port == 465:
        smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=60)
    else:
        smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=60)
        smtp.starttls()
    with smtp as s:
        s.login(cfg.mail_user, cfg.mail_password)
        s.send_message(m)
    return m
