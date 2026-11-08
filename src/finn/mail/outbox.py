# mail/outbox.py
import smtplib
from email.message import EmailMessage

def reply(cfg, orig, html, text):
    m = EmailMessage()
    m["From"], m["To"] = cfg.user, orig.reply_to[0] if orig.reply_to else orig.from_
    m["Subject"] = "Re: " + orig.subject
    mid = orig.headers.get("message-id", ("",))[0]
    m["In-Reply-To"] = m["References"] = mid
    m.set_content(text)
    m.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(cfg.smtp_host, 465) as s:
        s.login(cfg.user, cfg.password)
        s.send_message(m)