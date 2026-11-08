"""Postfach per IMAP: ungelesene Aufträge holen, IDLE warten, verarbeitete UIDs merken."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from imap_tools import AND, MailBox, MailMessage, MailMessageFlags

log = logging.getLogger("finn.inbox")


class UidSpeicher:
    """Bereits verarbeitete UIDs je Konto/Ordner/UIDVALIDITY (JSON-Datei, atomar geschrieben)."""

    def __init__(self, pfad: Path):
        self.pfad = pfad
        try:
            self._daten: dict[str, list[str]] = json.loads(pfad.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._daten = {}

    @staticmethod
    def schluessel(user: str, ordner: str, uidvalidity: int | str) -> str:
        return f"{user}|{ordner}|{uidvalidity}"

    def enthaelt(self, schluessel: str, uid: str) -> bool:
        return uid in self._daten.get(schluessel, [])

    def merke(self, schluessel: str, uid: str) -> None:
        uids = self._daten.setdefault(schluessel, [])
        if uid not in uids:
            uids.append(uid)
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.pfad.parent, prefix=".uids-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self._daten, f, indent=1)
        os.replace(tmp, self.pfad)


class Postfach:
    """Kontextmanager um imap-tools; holt ungelesene, noch nicht verarbeitete Mails."""

    def __init__(self, cfg, speicher: UidSpeicher, ordner: str = "INBOX"):
        self.cfg = cfg
        self.speicher = speicher
        self.ordner = ordner
        self.mb: MailBox | None = None
        self.key = ""

    def __enter__(self) -> "Postfach":
        self.mb = MailBox(self.cfg.imap_host, self.cfg.imap_port, timeout=60).login(
            self.cfg.mail_user, self.cfg.mail_password, self.ordner
        )
        uv = self.mb.folder.status(self.ordner, ["UIDVALIDITY"])["UIDVALIDITY"]
        self.key = UidSpeicher.schluessel(self.cfg.mail_user, self.ordner, uv)
        log.info("IMAP verbunden: %s@%s/%s (UIDVALIDITY %s)", self.cfg.mail_user,
                 self.cfg.imap_host, self.ordner, uv)
        return self

    def __exit__(self, *exc) -> None:
        if self.mb is not None:
            try:
                self.mb.logout()
            except Exception:  # Verbindung ggf. schon weg
                pass
            self.mb = None

    def neue(self) -> list[MailMessage]:
        """Ungelesene Mails, die noch nicht verarbeitet wurden (werden NICHT als gelesen markiert)."""
        msgs = list(self.mb.fetch(AND(seen=False), mark_seen=False))
        neu = [m for m in msgs if not self.speicher.enthaelt(self.key, m.uid)]
        if len(neu) != len(msgs):
            log.info("%d ungelesene Mail(s) bereits verarbeitet, übersprungen", len(msgs) - len(neu))
        return neu

    def erledigt(self, msg: MailMessage) -> None:
        """Erst merken (lokal, maßgeblich), dann auf dem Server als gelesen markieren."""
        self.speicher.merke(self.key, msg.uid)
        self.mb.flag(msg.uid, MailMessageFlags.SEEN, True)

    def warte(self, timeout: float) -> None:
        self.mb.idle.wait(timeout=timeout)
