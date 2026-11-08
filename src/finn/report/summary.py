"""Zusammenfassung: Fakten für das LLM, Zahlenprüfung, deterministischer Fallback."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from finn.calc.covenants import Posten, VertragsErgebnis
from finn.report import format as fmt

_DATUM = re.compile(r"\b\d{1,2}\.\s?\d{1,2}\.\s?\d{4}\b")
_ZAHL = re.compile(r"(?<![\w.,])[+−-]?\d[\d.]*(?:,\d+)?")


def fakten(ergebnisse: list[VertragsErgebnis]) -> list[dict]:
    """Fertige, bereits formatierte Ergebnisse – die einzige Zahlenquelle für das LLM."""
    out = []
    for ve in ergebnisse:
        if ve.fehler:
            out.append({"vertrag": ve.name, "pruefung": "nicht möglich", "grund": ve.fehler})
        elif not ve.covenants:
            out.append({"vertrag": ve.name, "financial_covenants": "keine"})
        for e in ve.covenants:
            out.append({
                "vertrag": ve.name,
                "covenant": e.kennzahl,
                "wert": fmt.kennzahl(e.wert, e.einheit, e.rundung),
                "grenzwert": fmt.grenzwert(e.grenzwert, e.einheit, e.richtung, e.rundung),
                "headroom": fmt.headroom(e.headroom, e.einheit, e.rundung),
                "eingehalten": "ja" if e.eingehalten else "nein",
                "spielraum_bis_grenzwert": (
                    f"Grenzwert wäre erreicht {fmt.spielraum_satz(e.spielraum)}, übrige Planwerte unverändert"
                    if e.spielraum else "nicht ermittelbar"),
            })
    return out


def _parse(s: str) -> Decimal | None:
    s = s.replace("−", "-").replace("+", "")
    s = s.replace(".", "").replace(",", ".") if "," in s or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s) else s
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _alle_posten(posten: list[Posten]):
    for p in posten:
        yield p
        yield from _alle_posten(p.unterposten)


def erlaubte_zahlen(ergebnisse: list[VertragsErgebnis], stichtag: date) -> set[Decimal]:
    erlaubt: set[Decimal] = {Decimal(stichtag.year)}
    n_cov = sum(len(v.covenants) for v in ergebnisse)
    n_ok = sum(e.eingehalten for v in ergebnisse for e in v.covenants)
    n_mit = sum(bool(v.covenants) for v in ergebnisse)
    n_fehler = sum(bool(v.fehler) for v in ergebnisse)
    erlaubt |= {Decimal(x) for x in (len(ergebnisse), n_cov, n_ok, n_cov - n_ok, n_mit, n_fehler,
                                     len(ergebnisse) - n_mit, len(ergebnisse) - n_mit - n_fehler)}

    def add(x: Decimal, stellen: int):
        for s in {stellen, 0, 1, 2}:
            q = _parse(fmt.zahl(x, s))
            if q is not None:
                erlaubt.add(abs(q))

    for v in ergebnisse:
        for e in v.covenants:
            st = fmt.anzeige_stellen(e.rundung)
            for x in (e.wert, e.grenzwert, e.headroom):
                add(x, st)
            for x in (e.zaehler, e.nenner):
                add(x, 0)
            if e.spielraum:
                add(e.spielraum.aenderung, 0)
                add(e.spielraum.aenderung / 1000, 1)
            for p in _alle_posten(e.zaehler_posten + e.nenner_posten):
                add(p.wert, 0)
                add(abs(p.basis), 0)
    return erlaubt


def pruefe_zahlen(text: str, erlaubt: set[Decimal], stichtag: date) -> list[str]:
    """Liefert alle Zahlen im Text, die nicht in den Ergebnissen vorkommen."""
    fehler = []
    for d in _DATUM.findall(text):
        if d.replace(" ", "") != stichtag.strftime("%d.%m.%Y"):
            fehler.append(d)
    rest = _DATUM.sub(" ", text)
    for m in _ZAHL.findall(rest):
        m = m.rstrip(".")
        q = _parse(m)
        if q is None or abs(q) not in erlaubt:
            fehler.append(m)
    return fehler


def fallback(ergebnisse: list[VertragsErgebnis], stichtag: date) -> str:
    alle = [e for v in ergebnisse for e in v.covenants]
    gescheitert = [v for v in ergebnisse if v.fehler]
    ohne = [v for v in ergebnisse if not v.covenants and not v.fehler]
    verletzt = [e for e in alle if not e.eingehalten]
    s = [
        f"Von {len(ergebnisse)} Kreditverträgen enthalten {len(ergebnisse) - len(ohne) - len(gescheitert)} "
        f"insgesamt {len(alle)} Financial Covenants; auf Basis Plan {stichtag.year} "
        + (
            "sind alle eingehalten."
            if not verletzt
            else f"sind {len(verletzt)} nicht eingehalten: "
            + ", ".join(f"{e.kennzahl} ({e.vertrag})" for e in verletzt) + "."
        )
    ]
    if alle:
        knapp = min(alle, key=lambda e: e.headroom / e.grenzwert)
        s.append(
            f"Am knappsten ist {knapp.kennzahl} ({knapp.vertrag}) mit "
            f"{fmt.kennzahl(knapp.wert, knapp.einheit, knapp.rundung)} bei einem Grenzwert von "
            f"{fmt.grenzwert(knapp.grenzwert, knapp.einheit, knapp.richtung, knapp.rundung)} "
            f"(Headroom {fmt.headroom(knapp.headroom, knapp.einheit, knapp.rundung)})"
            + (f"; der Grenzwert wäre {fmt.spielraum_satz(knapp.spielraum)} erreicht "
               "(übrige Planwerte unverändert)" if knapp.spielraum else "")
            + "."
        )
        ebitda = [e for e in alle if e.spielraum and e.spielraum.treiber == "EBITDA"]
        if ebitda and knapp not in ebitda:
            eb = min(ebitda, key=lambda e: abs(e.spielraum.aenderung))
            s.append(
                f"Beim EBITDA ist der Spielraum für {eb.kennzahl} ({eb.vertrag}) am kleinsten: "
                f"Ein Rückgang um rd. {fmt.zahl(abs(eb.spielraum.aenderung) / 1000, 1)} Mio. € "
                f"würde den Grenzwert erreichen."
            )
    if ohne:
        s.append(
            "Ohne Financial Covenants: " + ", ".join(v.name for v in ohne) + "."
        )
    if gescheitert:
        s.append(
            "ACHTUNG – nicht geprüft werden konnte: " + ", ".join(v.name for v in gescheitert)
            + " (siehe Tabelle)."
        )
    return " ".join(s)


# --- Formulierung per Claude --------------------------------------------------

SYSTEM_PROMPT = """\
Du schreibst für eine Finanzabteilung die Zusammenfassung einer Covenant-Prüfung auf Planbasis.
Die Ergebnisse sind fertig berechnet. Du rechnest nicht und nennst ausschließlich Zahlen, die
wörtlich in den Fakten stehen (gleiche Schreibweise). Keine Paragraphen, keine Vertragsnummern,
keine Daten außer dem Stichtag.
Schreibe 2–3 sachliche Sätze auf Deutsch: Gesamtergebnis, knappste(r) Covenant(s) mit Wert,
Grenzwert und Headroom, dazu der Spielraum bis zum Grenzwert (aus "spielraum_bis_grenzwert",
z. B. "Ein EBITDA-Rückgang von rd. 1,5 Mio. € würde den Grenzwert erreichen"), ggf. Verträge
ohne Covenants oder nicht prüfbare Verträge. Planwerte dienen der Frühwarnung."""


class _Text(BaseModel):
    text: str


def formuliere(client, modell: str, fakten_: list[dict], stichtag: date) -> str:
    from finn.extraction.llm import parse

    import json

    out = parse(
        client, modell, _Text, SYSTEM_PROMPT,
        [{"type": "text", "text": f"Stichtag: {stichtag:%d.%m.%Y}\nFakten:\n"
          + json.dumps(fakten_, ensure_ascii=False, indent=1)}],
        max_tokens=4000, zweck="Zusammenfassung",
    )
    return out.text.strip()


def ohne_namen(text: str, ergebnisse: list[VertragsErgebnis]) -> str:
    """Vertragsnamen (enthalten Nummern) vor der Zahlenprüfung ausblenden."""
    for ve in sorted(ergebnisse, key=lambda v: -len(v.name)):
        text = text.replace(ve.name, " ")
    return text
