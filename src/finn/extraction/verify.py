"""Prüft per pymupdf, ob jedes von Claude gelieferte Zitat auf der angegebenen Seite steht."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pymupdf

from finn.extraction.schema import Vertrag, iter_fundstellen

_ZEICHEN = str.maketrans({
    "„": '"', "“": '"', "”": '"', "‚": "'", "‘": "'", "’": "'", "«": '"', "»": '"',
    "–": "-", "—": "-", "−": "-", "­": "", " ": " ",
})


def normalisiere(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(_ZEICHEN).casefold()
    s = re.sub(r"\s+", " ", s).strip()
    return s.strip(" .,;:")


def _ohne_trennung(s: str) -> str:
    # "Verlust- rechnung" (Zeilenumbruch-Trennung) → "verlustrechnung"
    return re.sub(r"(\w)- (\w)", r"\1\2", s)


@dataclass(frozen=True)
class Pruefung:
    seite: int
    zitat: str
    gefunden: bool
    gefunden_auf: int | None = None  # andere Seite, falls dort vorhanden


def seitentexte(pdf: bytes) -> list[str]:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return [normalisiere(p.get_text()) for p in doc]


def _enthalten(zitat: str, seite: str) -> bool:
    return zitat in seite or _ohne_trennung(zitat) in _ohne_trennung(seite)


def pruefe_zitat(seiten: list[str], seite: int, zitat: str) -> Pruefung:
    z = normalisiere(zitat)
    if not z:
        return Pruefung(seite, zitat, False)
    if 1 <= seite <= len(seiten) and _enthalten(z, seiten[seite - 1]):
        return Pruefung(seite, zitat, True)
    anders = next((i + 1 for i, s in enumerate(seiten) if _enthalten(z, s)), None)
    return Pruefung(seite, zitat, False, anders)


def pruefe_vertrag(pdf: bytes, v: Vertrag) -> list[Pruefung]:
    seiten = seitentexte(pdf)
    gesehen: dict[tuple[int, str], Pruefung] = {}
    for f in iter_fundstellen(v):
        key = (f.seite, f.zitat)
        if key not in gesehen:
            gesehen[key] = pruefe_zitat(seiten, f.seite, f.zitat)
    return list(gesehen.values())


def _de(x: float) -> list[str]:
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    varianten = {s, f"{x:.1f}", f"{x:.2f}"}
    return [v.replace(".", ",") for v in varianten]


def pruefe_grenzwerte(v: Vertrag) -> list[str]:
    """Steht die von Claude gelieferte Zahl auch im zitierten Wortlaut? (Plausibilität)"""
    warnungen = []
    for c in v.covenants:
        for g in c.grenzwerte:
            z = normalisiere(g.fundstelle.zitat)
            if not any(x in z for x in _de(g.wert)):
                warnungen.append(
                    f"{c.kennzahl}: Grenzwert {_de(g.wert)[0]} steht nicht im zitierten Wortlaut "
                    f"(S. {g.fundstelle.seite}) – bitte manuell prüfen."
                )
    return warnungen
