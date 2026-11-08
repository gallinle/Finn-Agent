"""Zusammenfassung: Fakten für das LLM, Zahlenprüfung, deterministischer Fallback."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from finn.calc.covenants import Posten, VertragsErgebnis
from finn.report import format as fmt

_DATUM = re.compile(r"\b\d{1,2}\.\s?\d{1,2}\.\s?\d{4}\b")
_ZAHL = re.compile(r"(?<![\w.,])[+−-]?\d[\d.]*(?:,\d+)?")


def fakten(ergebnisse: list[VertragsErgebnis]) -> list[dict]:
    """Fertige, bereits formatierte Ergebnisse – die einzige Zahlenquelle für das LLM."""
    out = []
    for ve in ergebnisse:
        if not ve.covenants:
            out.append({"vertrag": ve.vertrag.vertragsname, "financial_covenants": "keine"})
        for e in ve.covenants:
            out.append({
                "vertrag": ve.vertrag.vertragsname,
                "covenant": e.kennzahl,
                "wert": fmt.kennzahl(e.wert, e.einheit, e.rundung),
                "grenzwert": fmt.grenzwert(e.grenzwert, e.einheit, e.richtung, e.rundung),
                "headroom": fmt.headroom(e.headroom, e.einheit, e.rundung),
                "eingehalten": "ja" if e.eingehalten else "nein",
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
    erlaubt |= {Decimal(x) for x in (len(ergebnisse), n_cov, n_ok, n_cov - n_ok, n_mit,
                                     len(ergebnisse) - n_mit)}

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
    ohne = [v for v in ergebnisse if not v.covenants]
    verletzt = [e for e in alle if not e.eingehalten]
    s = [
        f"Von {len(ergebnisse)} Kreditverträgen enthalten {len(ergebnisse) - len(ohne)} "
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
            f"(Headroom {fmt.headroom(knapp.headroom, knapp.einheit, knapp.rundung)})."
        )
    if ohne:
        s.append(
            "Ohne Financial Covenants: " + ", ".join(v.vertrag.vertragsname for v in ohne) + "."
        )
    return " ".join(s)
