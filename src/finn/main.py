"""Finn – Covenant-Prüfung per E-Mail. Polling-Schleife über das Postfach.

    python -m finn.main             # Dauerbetrieb (IMAP IDLE)
    python -m finn.main --einmal    # ungelesene Aufträge einmal abarbeiten, dann Ende
    python -m finn.main --trocken   # nichts senden/markieren, Antworten nach out/<uid>/
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

from imap_tools import MailMessage

from finn.config import PROJEKT_ROOT, Config, lade_config
from finn.dienste import Dienste
from finn.mail import outbox
from finn.mail.inbox import Postfach, UidSpeicher
from finn.mail.outbox import Antwort
from finn.pipeline import verarbeite

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


def bearbeite_neue(postfach, dienste: Dienste, cfg: Config, sende: Sender) -> int:
    """Alle neuen Aufträge einmal abarbeiten. Gibt die Zahl der erledigten Mails zurück."""
    erledigt = 0
    for msg in postfach.neue():
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
        antwort = verarbeite(msg, dienste, cfg)
        try:
            sende(antwort)
        except Exception:
            log.exception("Versand an %s fehlgeschlagen – uid=%s bleibt offen", antwort.an, msg.uid)
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Finn – Covenant-Prüfung per E-Mail")
    ap.add_argument("--einmal", action="store_true", help="einmal abarbeiten, dann beenden")
    ap.add_argument("--trocken", action="store_true",
                    help="nichts senden oder markieren; Antworten nach out/trocken/")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    cfg = lade_config()
    if fehlend := pruefe_config(cfg):
        log.error("Konfiguration unvollständig, bitte in .env setzen: %s", ", ".join(fehlend))
        return 2

    from finn.extraction.contracts import ClaudeDienste

    dienste = ClaudeDienste(cfg)
    speicher = UidSpeicher(cfg.cache_dir / "processed_uids.json")
    sende: Sender = (_trocken_sender(cfg, PROJEKT_ROOT / "out" / "trocken") if args.trocken
                     else lambda a: outbox.sende(cfg, a))

    log.info("Finn startet (%s) – Postfach %s", "trocken" if args.trocken else "live", cfg.mail_user)
    try:
        with Postfach(cfg, speicher) as postfach:
            p = _NurLesen(postfach) if args.trocken else postfach
            while True:
                bearbeite_neue(p, dienste, cfg, sende)
                if args.einmal:
                    return 0
                postfach.warte(cfg.poll_timeout)
    except KeyboardInterrupt:
        log.info("Beendet.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
