"""Wirtschaftsplan (xlsx) einlesen und indexieren.

Index: Blatt → Zeilenbeschriftung → {Spaltenkopf: Zelle(Wert, "Blatt!Zelle")}.
Für GuV/Bilanz sind die Spaltenköpfe die Jahre ("Plan 2027", "31.12.2027 (Plan)"),
im Darlehensspiegel die Messgrößen des Planjahres ("Zinsaufwand 2027", ...).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from decimal import Decimal

import openpyxl


class PlanFehler(Exception):
    """Die Datei ist kein lesbarer Wirtschaftsplan."""


@dataclass(frozen=True)
class Zelle:
    wert: Decimal
    ref: str  # z. B. "GuV!D18"


@dataclass
class Planindex:
    blaetter: dict[str, dict[str, dict[str, Zelle]]]
    notizen: dict[str, list[str]] = field(default_factory=dict)  # Texte ohne Zahlen je Blatt

    def get(self, blatt: str, zeile: str, spalte: str) -> Zelle:
        try:
            return self.blaetter[blatt][zeile][spalte]
        except KeyError:
            raise KeyError(f"Keine Zelle für {blatt} › {zeile} › {spalte}") from None

    def spalten(self, blatt: str) -> list[str]:
        out: list[str] = []
        for werte in self.blaetter[blatt].values():
            for s in werte:
                if s not in out:
                    out.append(s)
        return out

    def katalog(self) -> list[tuple[str, str, list[str]]]:
        """(Blatt, Zeile, verfügbare Spalten) – Auswahlliste für die Zuordnung."""
        return [
            (b, z, list(sp))
            for b, zeilen in self.blaetter.items()
            for z, sp in zeilen.items()
        ]


def _ist_zahl(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def lade_plan(daten: bytes) -> Planindex:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(daten), data_only=True)
    except Exception as e:  # zip/xml-Fehler etc.
        raise PlanFehler(f"Excel-Datei konnte nicht gelesen werden: {e}") from e

    blaetter: dict[str, dict[str, dict[str, Zelle]]] = {}
    notizen: dict[str, list[str]] = {}
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows()]
        texte_ohne_zahl = [
            " ".join(r[0].value.split())
            for r in rows
            if r and isinstance(r[0].value, str) and r[0].value.strip()
            and not any(_ist_zahl(c.value) for c in r[1:])
        ]
        if texte_ohne_zahl:
            notizen[ws.title] = texte_ohne_zahl
        kopf_idx = None
        for i, row in enumerate(rows[:15]):
            texte = [c for c in row[1:] if isinstance(c.value, str) and c.value.strip()]
            if len(texte) >= 2:
                kopf_idx = i
                break
        if kopf_idx is None:
            continue  # z. B. Deckblatt
        kopf = {
            c.column: c.value.strip()
            for c in rows[kopf_idx][1:]
            if isinstance(c.value, str) and c.value.strip()
        }
        zeilen: dict[str, dict[str, Zelle]] = {}
        for row in rows[kopf_idx + 1 :]:
            if not row or not isinstance(row[0].value, str):
                continue
            werte = {
                kopf[c.column]: Zelle(Decimal(str(c.value)), f"{ws.title}!{c.coordinate}")
                for c in row[1:]
                if c.column in kopf and _ist_zahl(c.value)
            }
            if not werte:
                continue  # Zwischenüberschrift / Erläuterung
            label = " ".join(row[0].value.split())
            if label in zeilen:
                label = f"{label} [Zeile {row[0].row}]"
            zeilen[label] = werte
        if zeilen:
            blaetter[ws.title] = zeilen
    wb.close()
    if not blaetter:
        raise PlanFehler("Die Excel-Datei enthält keine Tabellen mit Planwerten.")
    return Planindex(blaetter, notizen)
