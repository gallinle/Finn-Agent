"""Finn – Covenant-Prüfung per E-Mail. Polling-Schleife über das Postfach.

    python -m finn.main             # Dauerbetrieb (IMAP IDLE)
    python -m finn.main --einmal    # ungelesene Aufträge einmal abarbeiten, dann Ende
    python -m finn.main --trocken   # nichts senden/markieren, Antworten nach out/<uid>/
"""

from __future__ import annotations

import argparse
import fcntl
import imaplib
import logging
import re
import signal
import smtplib
import socket
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

from imap_tools import MailMessage
from imap_tools.errors import MailboxLoginError

from finn.config import PROJEKT_ROOT, Config, lade_config
from finn.dienste import Dienste
from finn.mail import outbox
from finn.mail.inbox import Postfach, UidSpeicher
from finn.mail.outbox import Antwort
from finn.pipeline import VoruebergehenderFehler, verarbeite

log = logging.getLogger("finn.main")

Sender = Callable[[Antwort], None]

_SYSTEM_ABSENDER = re.compile(r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce)", re.I)


def ist_automatisch(msg: MailMessage) -> str | None:
    """Grund, falls die Mail automatisch erzeugt ist (keine Antwort, sonst Mail-Schleifen)."""
    h = {k.lower(): " ".join(v) for k, v in msg.headers.items()}
    if h.get("auto-submitted", "no").strip().lower() != "no":
        return f"Auto-Submitted: {h['auto-submitted']}"
    if h.get("precedence", "").strip().lower() in {"bulk", "junk", "list", "auto_reply"}:
        return f"Precedence: {h['precedence']}"
    if "list-id" in h or "list-unsubscribe" in h:
        return "Mailingliste"
    if _SYSTEM_ABSENDER.match((msg.from_ or "").partition("@")[0]):
        return f"Systemabsender {msg.from_}"
    return None


@dataclass
class Zustand:
    """Versuchszähler je UID über mehrere Durchläufe (nur im Speicher)."""

    max_ki_versuche: int = 3
    max_sendeversuche: int = 3
    ki_versuche: Counter = field(default_factory=Counter)
    sendeversuche: Counter = field(default_factory=Counter)
    aufgegeben: set[str] = field(default_factory=set)


def bearbeite_neue(postfach, dienste: Dienste, cfg: Config, sende: Sender,
                   zustand: Zustand | None = None) -> int:
    """Alle neuen Aufträge einmal abarbeiten. Gibt die Zahl der erledigten Mails zurück."""
    zustand = zustand or Zustand()
    erledigt = 0
    for msg in postfach.neue():
        if msg.uid in zustand.aufgegeben:
            continue
        absender = (msg.from_ or "").lower()
        log.info("Mail uid=%s von %s: %r", msg.uid, msg.from_, msg.subject)
        if absender == cfg.mail_user.lower():
            log.info("uid=%s stammt vom eigenen Konto – keine Antwort", msg.uid)
            postfach.erledigt(msg)
            continue
        if grund := ist_automatisch(msg):
            log.info("uid=%s ist automatisch erzeugt (%s) – keine Antwort", msg.uid, grund)
            postfach.erledigt(msg)
            continue
        zustand.ki_versuche[msg.uid] += 1
        letzter = zustand.ki_versuche[msg.uid] >= zustand.max_ki_versuche
        try:
            antwort = verarbeite(msg, dienste, cfg, letzter_versuch=letzter)
        except VoruebergehenderFehler as e:
            log.warning("uid=%s: KI-Dienst nicht erreichbar (Versuch %d/%d): %s – später erneut",
                        msg.uid, zustand.ki_versuche[msg.uid], zustand.max_ki_versuche, e)
            continue
        try:
            sende(antwort)
        except Exception:
            zustand.sendeversuche[msg.uid] += 1
            n = zustand.sendeversuche[msg.uid]
            if n >= zustand.max_sendeversuche:
                zustand.aufgegeben.add(msg.uid)
                log.exception("Versand an %s endgültig fehlgeschlagen (%d Versuche) – uid=%s bleibt "
                              "ungelesen und wird erst nach Neustart erneut versucht", antwort.an, n, msg.uid)
            else:
                log.exception("Versand an %s fehlgeschlagen (Versuch %d/%d) – uid=%s bleibt offen",
                              antwort.an, n, zustand.max_sendeversuche, msg.uid)
            continue
        log.info("%s an %s gesendet (uid=%s)", "Fehler-Antwort" if antwort.ist_fehler else "Antwort",
                 antwort.an, msg.uid)
        postfach.erledigt(msg)
        erledigt += 1
    return erledigt


def _trocken_sender(cfg: Config, ziel: Path) -> Sender:
    def sende(a: Antwort) -> None:
        d = ziel / time.strftime("%Y%m%d-%H%M%S")
        d.mkdir(parents=True, exist_ok=True)
        (d / "antwort.html").write_text(a.html, encoding="utf-8")
        (d / "antwort.eml").write_bytes(bytes(outbox.baue_email(a, cfg.mail_user)))
        log.info("[trocken] Antwort an %s nach %s geschrieben", a.an, d)
    return sende


class _NurLesen:
    """Postfach-Wrapper für --trocken: markiert nichts."""

    def __init__(self, p: Postfach):
        self.p = p

    def neue(self) -> list[MailMessage]:
        return self.p.neue()

    def erledigt(self, msg: MailMessage) -> None:
        log.info("[trocken] uid=%s würde als erledigt markiert", msg.uid)


def pruefe_config(cfg: Config) -> list[str]:
    fehlend = [n for n, v in (("IMAP_HOST", cfg.imap_host), ("SMTP_HOST", cfg.smtp_host),
                              ("MAIL_USER", cfg.mail_user), ("MAIL_PASSWORD", cfg.mail_password)) if not v]
    return fehlend


# Verbindungsfehler, nach denen neu verbunden wird
VERBINDUNGS_FEHLER = (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError, socket.timeout,
                      smtplib.SMTPServerDisconnected)


def richte_logging_ein(log_dir: Path) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    konsole = logging.StreamHandler()
    konsole.setFormatter(fmt)
    log_dir.mkdir(parents=True, exist_ok=True)
    datei = RotatingFileHandler(log_dir / "finn.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    datei.setFormatter(fmt)
    root.handlers[:] = [konsole, datei]
    for laut in ("httpx2", "httpx", "anthropic"):
        logging.getLogger(laut).setLevel(logging.WARNING)


class Sperre:
    """Verhindert zwei gleichzeitig laufende Instanzen (Doppelverarbeitung)."""

    def __init__(self, pfad: Path):
        self.pfad = pfad
        self.f = None

    def __enter__(self):
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.pfad, "w")
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.f.close()
            raise RuntimeError(f"Finn läuft bereits (Sperre {self.pfad})") from None
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _sigterm(*_):
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Finn – Covenant-Prüfung per E-Mail")
    ap.add_argument("--einmal", action="store_true", help="einmal abarbeiten, dann beenden")
    ap.add_argument("--trocken", action="store_true",
                    help="nichts senden oder markieren; Antworten nach out/trocken/")
    args = ap.parse_args(argv)
    richte_logging_ein(PROJEKT_ROOT / "logs")
    signal.signal(signal.SIGTERM, _sigterm)

    cfg = lade_config()
    if fehlend := pruefe_config(cfg):
        log.error("Konfiguration unvollständig, bitte in .env setzen: %s", ", ".join(fehlend))
        return 2

    from finn.extraction.contracts import ClaudeDienste

    dienste = ClaudeDienste(cfg)
    speicher = UidSpeicher(cfg.cache_dir / "processed_uids.json")
    sende: Sender = (_trocken_sender(cfg, PROJEKT_ROOT / "out" / "trocken") if args.trocken
                     else lambda a: outbox.sende(cfg, a))

    # Bei --einmal gibt es keinen späteren Durchlauf → sofort Fehler-Antwort statt Wiederholung
    zustand = Zustand(max_ki_versuche=1 if args.einmal else 3)
    log.info("Finn startet (%s) – Postfach %s", "trocken" if args.trocken else "live", cfg.mail_user)
    try:
        with Sperre(cfg.cache_dir / "finn.lock"):
            return _schleife(cfg, dienste, speicher, sende, zustand, args.einmal, args.trocken)
    except KeyboardInterrupt:
        log.info("Beendet.")
        return 0
    except RuntimeError as e:
        log.error("%s", e)
        return 1


def _schleife(cfg, dienste, speicher, sende, zustand, einmal: bool, trocken: bool) -> int:
    pause = 5
    while True:
        try:
            with Postfach(cfg, speicher) as postfach:
                pause = 5  # Verbindung steht → Backoff zurücksetzen
                p = _NurLesen(postfach) if trocken else postfach
                while True:
                    bearbeite_neue(p, dienste, cfg, sende, zustand)
                    if einmal:
                        return 0
                    postfach.warte(cfg.poll_timeout)
        except MailboxLoginError as e:
            log.critical("IMAP-Anmeldung abgelehnt – MAIL_USER/MAIL_PASSWORD prüfen: %s", e)
            return 2
        except VERBINDUNGS_FEHLER as e:
            if einmal:
                log.error("Verbindungsfehler: %s", e)
                return 1
            log.warning("Verbindung unterbrochen (%s: %s) – neuer Versuch in %ds",
                        type(e).__name__, e, pause)
            time.sleep(pause)
            pause = min(pause * 2, 300)


if __name__ == "__main__":
    sys.exit(main())
