"""Postfach per IMAP: ungelesene Aufträge holen, IDLE warten, verarbeitete UIDs merken."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
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
    """Kontextmanager um imap-tools; holt ungelesene, noch nicht verarbeitete Mails.

    Gelesen werden der Posteingang und – falls `spam_filter` gesetzt – der Spam-Ordner
    (IMAP-Flag \\Junk). Aus dem Spam-Ordner werden nur Mails übernommen, die der Filter als
    möglichen Auftrag erkennt; beantwortete Aufträge werden in den Posteingang verschoben.
    """

    def __init__(self, cfg, speicher: UidSpeicher, ordner: str = "INBOX",
                 spam_filter: Callable[[MailMessage], bool] | None = None):
        self.cfg = cfg
        self.speicher = speicher
        self.ordner = ordner
        self.spam_filter = spam_filter
        self.spam: str | None = None
        self.mb: MailBox | None = None
        self.keys: dict[str, str] = {}

    def __enter__(self) -> "Postfach":
        self.mb = MailBox(self.cfg.imap_host, self.cfg.imap_port, timeout=60).login(
            self.cfg.mail_user, self.cfg.mail_password, self.ordner
        )
        if self.spam_filter is not None:
            self.spam = next((f.name for f in self.mb.folder.list() if "\\Junk" in f.flags), None)
        for o in self.ordner_liste:
            uv = self.mb.folder.status(o, ["UIDVALIDITY"])["UIDVALIDITY"]
            self.keys[o] = UidSpeicher.schluessel(self.cfg.mail_user, o, uv)
        log.info("IMAP verbunden: %s@%s, Ordner %s", self.cfg.mail_user, self.cfg.imap_host,
                 self.ordner_liste)
        return self

    def __exit__(self, *exc) -> None:
        if self.mb is not None:
            try:
                self.mb.logout()
            except Exception:  # Verbindung ggf. schon weg
                pass
            self.mb = None

    @property
    def ordner_liste(self) -> list[str]:
        return [self.ordner] + ([self.spam] if self.spam else [])

    @property
    def key(self) -> str:  # Schlüssel des Posteingangs (Kompatibilität)
        return self.keys[self.ordner]

    def neue(self) -> list[MailMessage]:
        """Ungelesene, noch nicht verarbeitete Mails (werden NICHT als gelesen markiert)."""
        neu: list[MailMessage] = []
        try:
            for o in self.ordner_liste:
                self.mb.folder.set(o)
                for m in self.mb.fetch(AND(seen=False), mark_seen=False):
                    if self.speicher.enthaelt(self.keys[o], m.uid):
                        continue
                    if o != self.ordner and not self.spam_filter(m):
                        continue  # echter Spam: nicht anfassen, nicht beantworten
                    if o != self.ordner:
                        log.info("Möglicher Auftrag im Spam-Ordner: uid=%s von %s", m.uid, m.from_)
                    m.finn_ordner = o
                    neu.append(m)
        finally:
            self.mb.folder.set(self.ordner)
        return neu

    def erledigt(self, msg: MailMessage, beantwortet: bool = True) -> None:
        """Erst merken (lokal, maßgeblich), dann auf dem Server als gelesen markieren.

        Beantwortete Aufträge aus dem Spam-Ordner werden in den Posteingang verschoben.
        """
        o = getattr(msg, "finn_ordner", self.ordner)
        self.speicher.merke(self.keys[o], msg.uid)
        if o == self.ordner:
            self.mb.flag(msg.uid, MailMessageFlags.SEEN, True)
            return
        try:
            self.mb.folder.set(o)
            self.mb.flag(msg.uid, MailMessageFlags.SEEN, True)
            if beantwortet:
                self.mb.move(msg.uid, self.ordner)
                log.info("uid=%s aus %s in den Posteingang verschoben", msg.uid, o)
        finally:
            self.mb.folder.set(self.ordner)

    def warte(self, timeout: float) -> None:
        self.mb.idle.wait(timeout=timeout)
