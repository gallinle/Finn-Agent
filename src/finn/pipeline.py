"""Fester Ablauf: Auftrags-Mail → Covenant-Prüfung → Antwort-Mail.

Keine Agent-Schleife: jeder Schritt wird genau einmal in fester Reihenfolge ausgeführt.

CLI (ohne Postfach):
    python -m finn.pipeline tests/fixtures/auftrag.eml [--offline] [--out out/]
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import anthropic
from imap_tools import MailMessage
from pydantic import ValidationError

from finn.calc.covenants import BerechnungsFehler, VertragsErgebnis, berechne_vertrag
from finn.config import PROJEKT_ROOT, Config, lade_config
from finn.dienste import Dienste, OfflineDienste
from finn.extraction import verify
from finn.mail.outbox import Antwort, baue_email
from finn.extraction.llm import LLMFehler
from finn.plan.wirtschaftsplan import PlanFehler, Planindex, lade_plan
from finn.report import summary
from finn.report.render import render, render_fehler

log = logging.getLogger("finn.pipeline")


class AuftragsFehler(Exception):
    """Fehler, der dem Absender verständlich erklärt werden kann."""

    def __init__(self, grund: str, details: str | None = None):
        super().__init__(grund)
        self.grund = grund
        self.details = details


class VoruebergehenderFehler(Exception):
    """KI-Dienst vorübergehend nicht erreichbar – Auftrag später erneut versuchen."""


class KonfigurationsFehler(Exception):
    """KI-Dienst nicht nutzbar (Schlüssel/Berechtigung) – Betreiber muss eingreifen."""


def _klassifiziere(e: Exception) -> Exception:
    if isinstance(e, (anthropic.APIConnectionError, anthropic.RateLimitError,
                      anthropic.InternalServerError)):
        return VoruebergehenderFehler(f"{type(e).__name__}: {e}")
    if isinstance(e, anthropic.APIStatusError) and e.status_code >= 500:
        return VoruebergehenderFehler(f"{type(e).__name__} ({e.status_code})")
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return KonfigurationsFehler(f"{type(e).__name__}: {e.message}")
    return e


# Fehler, die nur einen Vertrag betreffen – die übrigen werden trotzdem geprüft
VERTRAGS_FEHLER = (LLMFehler, BerechnungsFehler, ValidationError, KeyError, anthropic.BadRequestError)


@dataclass
class Lauf:
    antwort: Antwort
    ergebnisse: list[VertragsErgebnis]


# --- Mail-Helfer -------------------------------------------------------------


def _header(msg: MailMessage, name: str) -> str:
    v = msg.headers.get(name.lower(), ("",))
    return " ".join(v[0].split()) if v else ""


def antwort_huelle(msg: MailMessage) -> dict:
    an = msg.reply_to[0] if msg.reply_to else msg.from_
    betreff = msg.subject or "Covenant-Prüfung"
    if not betreff.lower().startswith(("re:", "aw:")):
        betreff = "Re: " + betreff
    mid = _header(msg, "Message-ID")
    refs = " ".join(x for x in (_header(msg, "References"), mid) if x)
    return dict(an=an, betreff=betreff, in_reply_to=mid, references=refs)


_ANDERE_FORMATE = (".xls", ".xlsm", ".xlsb", ".ods", ".csv", ".numbers")


def finde_plan_anhang(msg: MailMessage):
    xlsx = [a for a in msg.attachments if (a.filename or "").lower().endswith(".xlsx")]
    if not xlsx:
        namen = ", ".join(a.filename or "(ohne Namen)" for a in msg.attachments) or "keine"
        andere = [a.filename for a in msg.attachments
                  if (a.filename or "").lower().endswith(_ANDERE_FORMATE)]
        if andere:
            raise AuftragsFehler(
                "Der Wirtschaftsplan liegt nicht im Format .xlsx vor.",
                f"Gefunden: {', '.join(andere)}. Bitte die Datei in Excel als "
                "„Excel-Arbeitsmappe (.xlsx)“ speichern und erneut senden.",
            )
        raise AuftragsFehler(
            "Im Auftrag wurde kein Wirtschaftsplan als Excel-Datei (.xlsx) gefunden.",
            f"Gefundene Anhänge: {namen}.",
        )
    if len(xlsx) > 1:
        raise AuftragsFehler(
            "Der Auftrag enthält mehrere Excel-Dateien; bitte genau einen Wirtschaftsplan anhängen.",
            "Gefundene Excel-Anhänge: " + ", ".join(a.filename for a in xlsx) + ".",
        )
    return xlsx[0]


def lade_und_pruefe_plan(anhang, planjahr: int) -> Planindex:
    if not anhang.payload:
        raise AuftragsFehler(f"Der Anhang „{anhang.filename}“ ist leer.")
    try:
        plan = lade_plan(anhang.payload)
    except PlanFehler as e:
        raise AuftragsFehler(
            f"Der Anhang „{anhang.filename}“ konnte nicht als Wirtschaftsplan gelesen werden.",
            f"{e} Ist die Datei beschädigt, passwortgeschützt oder keine Excel-Arbeitsmappe?",
        ) from e
    spalten = {s for b in plan.blaetter for s in plan.spalten(b)}
    if not any(str(planjahr) in s for s in spalten):
        raise AuftragsFehler(
            f"Der Wirtschaftsplan enthält keine Werte für das Planjahr {planjahr}.",
            "Gefundene Spalten: " + ", ".join(sorted(spalten)) + ".",
        )
    return plan


# --- Ablauf ------------------------------------------------------------------


def pruefe(msg: MailMessage, dienste: Dienste, cfg: Config) -> Lauf:
    huelle = antwort_huelle(msg)

    # 1. Anhang + Wirtschaftsplan indexieren
    anhang = finde_plan_anhang(msg)
    plan = lade_und_pruefe_plan(anhang, cfg.planjahr)
    log.info("Plan %s: Blätter %s", anhang.filename, list(plan.blaetter))

    # 2. Verträge lesen (LLM) → 3. Zuordnung (LLM) → 4. Berechnung (Code)
    pdfs = sorted(cfg.vertraege_dir.glob("*.pdf"))
    if not pdfs:
        raise RuntimeError(f"Keine Vertrags-PDFs in {cfg.vertraege_dir}")
    ergebnisse = []
    nicht_gefunden: set[tuple[int, str]] = set()
    hinweise: list[str] = []
    for pdf in pdfs:
        daten = pdf.read_bytes()
        vertrag = None
        try:
            vertrag = dienste.extrahiere(daten, pdf.name)
            log.info("%s: %d Covenant(s)", pdf.name, len(vertrag.covenants))
            # Zitate gegen das PDF prüfen (pymupdf)
            for p in verify.pruefe_vertrag(daten, vertrag):
                if not p.gefunden:
                    nicht_gefunden.add((p.seite, p.zitat))
                    ort = f" (steht auf S. {p.gefunden_auf})" if p.gefunden_auf else ""
                    hinweise.append(f"{pdf.name}: Zitat „{p.zitat}“ nicht auf S. {p.seite} gefunden{ort}.")
            hinweise += [f"{pdf.name}: {w}" for w in verify.pruefe_grenzwerte(vertrag)]
            zuordnung = dienste.ordne_zu(vertrag, plan, pdf.name)
            ergebnisse.append(berechne_vertrag(pdf.name, vertrag, zuordnung, plan, cfg.stichtag))
        except anthropic.APIError as e:
            k = _klassifiziere(e)
            if k is not e:
                raise k from e
            log.exception("%s: API-Fehler", pdf.name)
            ergebnisse.append(VertragsErgebnis.fehlgeschlagen(pdf.name, vertrag, f"KI-Anfrage abgelehnt ({type(e).__name__})."))
        except VERTRAGS_FEHLER as e:
            log.exception("%s: Prüfung nicht möglich", pdf.name)
            grund = ("Die Antwort der KI entsprach nicht dem erwarteten Format."
                     if isinstance(e, ValidationError) else str(e).strip("'\""))
            ergebnisse.append(VertragsErgebnis.fehlgeschlagen(pdf.name, vertrag, grund))

    # 5. Zusammenfassung (LLM formuliert, Code prüft jede Zahl)
    fakten = summary.fakten(ergebnisse)
    try:
        text = dienste.fasse_zusammen(ergebnisse, fakten)
    except (anthropic.APIError, LLMFehler) as e:  # Zusammenfassung ist verzichtbar
        log.warning("Zusammenfassung per KI fehlgeschlagen (%s) – Standardtext", e)
        text = None
    if text:
        fremd = summary.pruefe_zahlen(summary.ohne_namen(text, ergebnisse),
                                      summary.erlaubte_zahlen(ergebnisse, cfg.stichtag),
                                      cfg.stichtag)
        if fremd:
            log.warning("Zusammenfassung verworfen, unbelegte Zahlen: %s", fremd)
            text = None
    if not text:
        text = summary.fallback(ergebnisse, cfg.stichtag)

    # 6. Rendern
    log.info("Zitate: %d nicht verifiziert", len(nicht_gefunden))
    html, plain = render(ergebnisse, text, cfg.stichtag, anhang.filename,
                         nicht_gefunden=nicht_gefunden, hinweise=hinweise)
    return Lauf(Antwort(html=html, text=plain, **huelle), ergebnisse)


def verarbeite(msg: MailMessage, dienste: Dienste, cfg: Config,
               letzter_versuch: bool = True) -> Antwort:
    """Wie `pruefe`, aber jeder Fehler wird zu einer verständlichen Fehler-Antwort.

    Vorübergehende Fehler des KI-Dienstes werden weitergereicht, solange nicht
    `letzter_versuch` – der Aufrufer kann den Auftrag dann später erneut versuchen.
    """
    huelle = antwort_huelle(msg)
    try:
        return pruefe(msg, dienste, cfg).antwort
    except VoruebergehenderFehler as e:
        if not letzter_versuch:
            raise
        log.error("KI-Dienst dauerhaft nicht erreichbar: %s", e)
        html, text = render_fehler(
            "Der KI-Dienst zum Lesen der Verträge ist derzeit nicht erreichbar.",
            "Mehrere Versuche sind fehlgeschlagen. Bitte senden Sie den Auftrag später erneut.",
        )
    except KonfigurationsFehler as e:
        log.critical("KI-Dienst nicht nutzbar – Konfiguration prüfen: %s", e)
        html, text = render_fehler(
            "Der KI-Dienst zum Lesen der Verträge ist derzeit nicht nutzbar (Konfigurationsfehler).",
            "Der Betreiber wurde über das Protokoll informiert. Bitte senden Sie den Auftrag später erneut.",
        )
    except AuftragsFehler as e:
        log.warning("Auftrag abgelehnt: %s", e.grund)
        html, text = render_fehler(e.grund, e.details)
    except Exception:
        fid = uuid.uuid4().hex[:8]
        log.exception("Interner Fehler bei der Verarbeitung [Fehler-ID %s]", fid)
        html, text = render_fehler(
            "Bei der Verarbeitung ist ein interner Fehler aufgetreten.",
            f"Fehler-ID {fid} – damit kann der Betreiber den Fall im Protokoll nachvollziehen.",
        )
    return Antwort(html=html, text=text, ist_fehler=True, **huelle)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Covenant-Prüfung für eine .eml-Datei")
    ap.add_argument("eml", type=Path)
    ap.add_argument("--out", type=Path, default=PROJEKT_ROOT / "out")
    ap.add_argument("--offline", action="store_true",
                    help="Referenzdaten statt Claude verwenden (tests/fixtures/referenz)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = lade_config()
    if args.offline:
        dienste: Dienste = OfflineDienste(PROJEKT_ROOT / "tests" / "fixtures" / "referenz")
    else:
        from finn.extraction.contracts import ClaudeDienste

        dienste = ClaudeDienste(cfg)
    msg = MailMessage.from_bytes(args.eml.read_bytes())
    antwort = verarbeite(msg, dienste, cfg)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "antwort.html").write_text(antwort.html, encoding="utf-8")
    (args.out / "antwort.txt").write_text(antwort.text, encoding="utf-8")
    (args.out / "antwort.eml").write_bytes(bytes(baue_email(antwort, cfg.mail_user or "finn@localhost")))
    print(f"{'FEHLER-Antwort' if antwort.ist_fehler else 'Antwort'} an {antwort.an}: {args.out}/antwort.html")
    return 1 if antwort.ist_fehler else 0


if __name__ == "__main__":
    sys.exit(main())
