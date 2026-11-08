# mail/inbox.py
from imap_tools import MailBox, AND

def poll(cfg, handle):
    with MailBox(cfg.imap_host).login(cfg.user, cfg.password, "INBOX") as mb:
        while True:
            for msg in mb.fetch(AND(seen=False), mark_seen=True):
                xlsx = [a for a in msg.attachments if a.filename.lower().endswith(".xlsx")]
                handle(msg, xlsx)            # msg.from_, msg.subject, msg.headers["message-id"]
            mb.idle.wait(timeout=60)