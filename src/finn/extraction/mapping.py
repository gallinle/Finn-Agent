"""Zuordnung Vertragsterm → Wirtschaftsplan-Zeile per Claude.

Claude wählt nur aus tatsächlich vorhandenen Zeilenbeschriftungen und Spalten: das Schema wird
pro Plan dynamisch mit Literal-Enums erzeugt. Der Code prüft das Ergebnis zusätzlich.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, Field, create_model

from finn.extraction.llm import LLMFehler, parse
from finn.extraction.schema import Quelle, TermZuordnung, Vertrag, Zuordnung, iter_terme
from finn.plan.wirtschaftsplan import Planindex
from finn.report.format import betrag

log = logging.getLogger("finn.mapping")
SEP = " › "

SYSTEM_PROMPT = """\
Du ordnest die Bestandteile vertraglicher Finanzkennzahlen den Positionen eines
Wirtschaftsplans zu. Du rechnest nicht. Du wählst ausschließlich Zeilen und Spalten aus dem
vorgegebenen Katalog.

Regeln:
- Verwende die Spalten des Planjahres (Plan bzw. Stichtag des Planjahres), nie Ist- oder
  Hochrechnungsspalten.
- Bilde die vertragliche Definition exakt ab, inklusive der Hinweise zu Ausschlüssen und
  Einschlüssen (z. B. nachrangige Gesellschafterdarlehen, Aufzinsung von Rückstellungen,
  Sondertilgungen). Nutze die Erläuterungen des Plans, um zu entscheiden, ob eine Position
  unter die Definition fällt.
- Ein Term kann aus mehreren Zellen bestehen (vorzeichen je Quelle, z. B. Gesamtposition
  minus enthaltene Teilposition). Bevorzuge eine Zeile, die den Term direkt abbildet.
- uebernahme="betrag", wenn der Plan die Position als Aufwand mit negativem Vorzeichen
  ausweist, der Term aber den Betrag meint (z. B. "zuzüglich Steuern", "Abschreibungen").
  uebernahme="wert" für Positionen, deren Vorzeichen Bedeutung hat (Jahresüberschuss/
  -fehlbetrag, Erträge, Bestände).
- Das Vorzeichen des Terms (zuzüglich/abzüglich) wendet der Code selbst an – bilde es nicht
  in der Quelle ab.
- Gibt es die Position im Plan nicht (z. B. keine außerordentlichen Posten ausgewiesen):
  quellen leer, nicht_im_plan=true, Begründung.
- Begründung: ein Satz, warum diese Zeile der Definition entspricht.
Ordne jede angegebene term_id genau einmal zu."""


def katalog_text(plan: Planindex, planjahr: int) -> str:
    teile = []
    for blatt, zeilen in plan.blaetter.items():
        teile.append(f"## Blatt {blatt}")
        for zeile, werte in zeilen.items():
            w = "; ".join(f"{s}: {betrag(z.wert)}" for s, z in werte.items())
            teile.append(f"- {blatt}{SEP}{zeile} | {w}")
    for blatt, notizen in plan.notizen.items():
        teile.append(f"## Erläuterungen {blatt}")
        teile.extend(f"- {n}" for n in notizen)
    return f"Planjahr: {planjahr}\n" + "\n".join(teile)


def _terme_text(v: Vertrag) -> tuple[list[str], str]:
    ids, zeilen = [], []
    kontext = {g.name: f"Zwischengröße {g.name}" for g in v.zwischengroessen}
    kontext |= {c.kennzahl: f"Covenant {c.kennzahl}: {c.definition_wortlaut}" for c in v.covenants}
    for tid, t in iter_terme(v):
        if t.art != "planposition":
            continue
        ids.append(tid)
        zeilen.append(json.dumps({
            "term_id": tid,
            "bezeichnung": t.bezeichnung,
            "vorzeichen_im_vertrag": "abzüglich" if t.vorzeichen < 0 else "zuzüglich",
            "hinweis": t.hinweis,
            "kontext": kontext.get(tid.split("/")[0]),
            "vertragswortlaut": t.fundstelle.zitat,
        }, ensure_ascii=False))
    return ids, "\n".join(zeilen)


def _schema(plan: Planindex, ids: list[str]) -> type[BaseModel]:
    zeilen = tuple(f"{b}{SEP}{z}" for b, z, _ in plan.katalog())
    spalten = tuple(sorted({s for b in plan.blaetter for s in plan.spalten(b)}))
    q = create_model(
        "PlanQuelle",
        zeile=(Literal[zeilen], Field(description="Blatt › Zeilenbeschriftung")),
        spalte=(Literal[spalten], ...),
        vorzeichen=(Literal[1, -1], 1),
        uebernahme=(Literal["wert", "betrag"], ...),
    )
    tz = create_model(
        "TermZuordnungPlan",
        term_id=(Literal[tuple(ids)], ...),
        quellen=(list[q], ...),
        nicht_im_plan=(bool, False),
        begruendung=(str, ...),
    )
    return create_model("ZuordnungPlan", zuordnungen=(list[tz], ...))


def pruefe(roh: BaseModel, plan: Planindex, ids: list[str], planjahr: int) -> tuple[Zuordnung, list[str]]:
    fehler, out = [], []
    gesehen = [z.term_id for z in roh.zuordnungen]
    for tid in ids:
        if gesehen.count(tid) != 1:
            fehler.append(f"term_id {tid} wurde {gesehen.count(tid)}-mal statt genau einmal zugeordnet")
    for z in roh.zuordnungen:
        quellen = []
        for q in z.quellen:
            blatt, _, zeile = q.zeile.partition(SEP)
            if q.spalte not in plan.blaetter.get(blatt, {}).get(zeile, {}):
                fehler.append(f"{z.term_id}: Spalte '{q.spalte}' existiert nicht für '{q.zeile}'")
            elif str(planjahr) not in q.spalte:
                fehler.append(f"{z.term_id}: Spalte '{q.spalte}' gehört nicht zum Planjahr {planjahr}")
            quellen.append(Quelle(blatt=blatt, zeile=zeile, spalte=q.spalte,
                                  vorzeichen=q.vorzeichen, uebernahme=q.uebernahme))
        if not quellen and not z.nicht_im_plan:
            fehler.append(f"{z.term_id}: keine Quelle, aber nicht_im_plan=false")
        out.append(TermZuordnung(term_id=z.term_id, quellen=quellen,
                                 nicht_im_plan=z.nicht_im_plan or not quellen,
                                 begruendung=z.begruendung))
    return Zuordnung(zuordnungen=out), fehler


def ordne_zu(client: anthropic.Anthropic, modell: str, v: Vertrag, plan: Planindex,
             planjahr: int, datei: str) -> Zuordnung:
    ids, terme = _terme_text(v)
    if not ids:
        return Zuordnung(zuordnungen=[])
    schema = _schema(plan, ids)
    content = [
        {"type": "text", "text": "# Wirtschaftsplan-Katalog\n" + katalog_text(plan, planjahr),
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"# Vertrag: {v.vertragsname}\n# Zuzuordnende Terme (JSON je Zeile)\n{terme}"},
    ]
    fehler: list[str] = []
    for versuch in (1, 2):  # fester zweiter Versuch mit Fehlerrückmeldung, keine Schleife
        if fehler:
            content = content + [{"type": "text", "text": "Dein letzter Vorschlag war ungültig:\n- "
                                  + "\n- ".join(fehler) + "\nBitte korrigiert vollständig neu zuordnen."}]
        roh = parse(client, modell, schema, SYSTEM_PROMPT, content, zweck=f"Zuordnung {datei} #{versuch}")
        z, fehler = pruefe(roh, plan, ids, planjahr)
        if not fehler:
            return z
        log.warning("Zuordnung %s ungültig: %s", datei, fehler)
    raise LLMFehler(f"Zuordnung {datei} ungültig: " + "; ".join(fehler))
