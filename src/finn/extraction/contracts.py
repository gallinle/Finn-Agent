"""Vertragsextraktion per Claude (mit Cache) und Claude-Implementierung der Dienste."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

import anthropic

from finn.config import Config
from finn.extraction import mapping
from finn.extraction.llm import parse
from finn.extraction.schema import Vertrag, Zuordnung
from finn.plan.wirtschaftsplan import Planindex
from finn.report import summary

log = logging.getLogger("finn.extraction")

SCHEMA_VERSION = 1

SYSTEM_PROMPT = """\
Du liest Kreditverträge wie eine erfahrene Finanzreferentin eines kommunalen Unternehmens.
Deine Aufgabe ist ausschließlich Lesen und Strukturieren. Du rechnest NIE: keine Kennzahlen,
keine Summen, keine Plan- oder Istwerte. Zahlen übernimmst du nur, wenn sie wörtlich im Vertrag
stehen (Grenzwerte, Prozentanteile, Margen).

Financial Covenants sind Finanzkennzahlen mit einem vertraglich einzuhaltenden Grenzwert
(Mindest- oder Höchstwert), deren Verletzung Rechtsfolgen hat. KEINE Covenants sind:
- historische Kennzahlen in Präambel oder Sachverhalt (z. B. "wies zum 31.12.2019 ... aus"),
- rein qualitative Klauseln (wesentliche Verschlechterung, Drittverzug, Negativerklärung),
- Preis-/Margenraster (diese gehören stattdessen in `margenraster`).

Für jeden Covenant:
- Löse die Definition vollständig auf, auch über Verweise auf Begriffsbestimmungen und Anlagen.
- Zähler und Nenner bestehen aus Termen. `planposition` = elementare Position aus GuV, Bilanz
  oder Finanzplan/Darlehensspiegel. Ist ein Term selbst ein im Vertrag definierter Sammelbegriff
  (z. B. EBITDA, Nettofinanzverbindlichkeiten, Schuldendienst), lege ihn als `zwischengroesse`
  an und verweise mit art="zwischengroesse" und exakt gleichem Namen darauf.
  Verwende keine Zwischengröße mit demselben Namen wie die Kennzahl selbst.
- vorzeichen: +1 für "zuzüglich"/Bestandteil, -1 für "abzüglich".
- faktor nur, wenn der Vertrag einen Anteil nennt (z. B. 0.5 für "50 % der Sonderposten").
- hinweis: vertragliche Bereinigungen, Ausschlüsse und Einschlüsse dieses Terms
  (z. B. "ohne Aufzinsung von Rückstellungen", "ohne Sondertilgungen",
  "einschließlich Gesellschafterdarlehen trotz Rangrücktritt", "ohne nachrangige
  Gesellschafterdarlehen"). Achte genau darauf – Verträge definieren gleiche Begriffe
  unterschiedlich.
- einheit "prozent" für Quoten in %, sonst "faktor"; richtung "min" oder "max".
- grenzwerte: bei Staffeln je Stufe ein Eintrag mit gueltig_ab/gueltig_bis (ISO-Datum).
- rundung_nachkommastellen nur, wenn der Vertrag eine Rundung vorschreibt.
- hinweise: Rechtsfolgen bei Abweichungen auf Planbasis, Heilungsrechte, Prüfzeitpunkte,
  Besonderheiten der Definition.

Fundstellen: `seite` ist die PDF-Seite (1-basiert; entspricht "Seite X von N" in der Fußzeile),
`paragraph` z. B. "§ 13 Abs. 1" oder "Anlage 3 Abs. 4 lit. a". `zitat` ist ein wörtlicher,
zusammenhängender Ausschnitt von genau dieser Seite (8–25 Wörter, ohne Auslassungen, ohne
Umformulierung) – er wird maschinell gegen das PDF geprüft.

Ohne Financial Covenants: hat_financial_covenants=false, covenants leer, kurze Begründung mit
Fundstelle (z. B. die Stelle, die ein Leser für einen Covenant halten könnte)."""

AUFGABE = (
    "Extrahiere aus diesem Kreditvertrag alle Financial Covenants mit vollständigen Definitionen "
    "(inkl. Anlagen, Bereinigungen, Tranchen, gestaffelter Grenzwerte), das Margenraster und "
    "die Fundstellen. vertragsname: Kreditgeber – Darlehensart und -nummer."
)


def pdf_hash(pdf: bytes) -> str:
    return hashlib.sha256(pdf).hexdigest()


class ClaudeDienste:
    def __init__(self, cfg: Config, client: anthropic.Anthropic | None = None,
                 nur_cache: bool = False):
        self.cfg = cfg
        self._client = client
        self.nur_cache = nur_cache
        self.extraktion_dir = cfg.cache_dir / "extraktion"
        self.zuordnung_dir = cfg.cache_dir / "zuordnung"

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            if self.nur_cache:
                raise RuntimeError("nur_cache=True, aber Cache-Eintrag fehlt")
            # Längste echte Extraktion ~105 s; 300 s × (1 + 2 Wiederholungen) begrenzt Hänger auf ~15 min
            self._client = anthropic.Anthropic(timeout=300.0, max_retries=2)
        return self._client

    # --- 1. Vertrag lesen -------------------------------------------------------

    def extrahiere(self, pdf: bytes, datei: str) -> Vertrag:
        pfad = self.extraktion_dir / f"{pdf_hash(pdf)}.json"
        if pfad.exists():
            daten = json.loads(pfad.read_text(encoding="utf-8"))
            if daten.get("schema_version") == SCHEMA_VERSION:
                log.info("%s: Extraktion aus Cache %s", datei, pfad.name)
                return Vertrag.model_validate(daten["vertrag"])
        vertrag = parse(
            self.client, self.cfg.modell, Vertrag, SYSTEM_PROMPT,
            [
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf",
                               "data": base64.standard_b64encode(pdf).decode()},
                    "title": datei,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": AUFGABE},
            ],
            max_tokens=21000,  # Obergrenze ohne Streaming (SDK: ≤ 10 min erwartete Dauer)
            zweck=f"Extraktion {datei}",
        )
        _schreibe(pfad, {"schema_version": SCHEMA_VERSION, "datei": datei,
                         "modell": self.cfg.modell, "vertrag": vertrag.model_dump(mode="json")})
        return vertrag

    # --- 2. Terme dem Plan zuordnen ---------------------------------------------

    def ordne_zu(self, vertrag: Vertrag, plan: Planindex, datei: str) -> Zuordnung:
        key = hashlib.sha256(
            (vertrag.model_dump_json() + mapping.katalog_text(plan, self.cfg.planjahr)).encode()
        ).hexdigest()
        pfad = self.zuordnung_dir / f"{key}.json"
        if pfad.exists():
            log.info("%s: Zuordnung aus Cache %s", datei, pfad.name)
            return Zuordnung.model_validate_json(pfad.read_text(encoding="utf-8"))
        z = mapping.ordne_zu(self.client, self.cfg.modell, vertrag, plan, self.cfg.planjahr, datei)
        _schreibe(pfad, json.loads(z.model_dump_json()))
        return z

    # --- 3. Zusammenfassung formulieren -----------------------------------------

    def fasse_zusammen(self, ergebnisse, fakten) -> str | None:
        if self.nur_cache:
            return None
        return summary.formuliere(self.client, self.cfg.modell, fakten, self.cfg.stichtag)


def _schreibe(pfad: Path, daten: dict) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
