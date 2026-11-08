"""Pydantic-Schemas für die strukturierte Ausgabe von Claude.

Claude liefert nur Struktur und Wortlaut (Terme, Vorzeichen, Faktoren laut Vertrag,
Grenzwerte, Fundstellen) – keine berechneten Werte.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, Field


class Fundstelle(BaseModel):
    seite: int = Field(description="PDF-Seite (1-basiert)")
    paragraph: str = Field(description='z. B. "§ 13 Abs. 1" oder "Anlage 3 Abs. 4"')
    zitat: str = Field(description="wörtliches, kurzes Zitat von genau dieser Seite")


class Term(BaseModel):
    bezeichnung: str = Field(
        description="Position laut Vertrag, bzw. exakter Name einer Zwischengröße"
    )
    art: Literal["planposition", "zwischengroesse"]
    vorzeichen: Literal[1, -1] = Field(description="+1 = zuzüglich, -1 = abzüglich")
    faktor: float = Field(1.0, description="Anteil laut Vertrag, z. B. 0.5 für '50 %'")
    hinweis: str | None = Field(
        None, description="Bereinigung/Ausschluss laut Vertrag, z. B. 'ohne Aufzinsung'"
    )
    fundstelle: Fundstelle


class Zwischengroesse(BaseModel):
    name: str = Field(description='z. B. "EBITDA", "Nettofinanzverbindlichkeiten"')
    terme: list[Term]
    fundstelle: Fundstelle


class Grenzwert(BaseModel):
    wert: float = Field(description="in der Einheit der Kennzahl, Prozent als 27.5")
    gueltig_ab: str | None = Field(None, description="ISO-Datum, falls gestaffelt")
    gueltig_bis: str | None = Field(None, description="ISO-Datum, falls gestaffelt")
    fundstelle: Fundstelle


class Hinweis(BaseModel):
    text: str
    fundstelle: Fundstelle


class Covenant(BaseModel):
    kennzahl: str = Field(description='z. B. "Dynamischer Verschuldungsgrad"')
    definition_wortlaut: str
    einheit: Literal["prozent", "faktor"]
    zaehler: list[Term]
    nenner: list[Term]
    richtung: Literal["min", "max"]
    grenzwerte: list[Grenzwert]
    rundung_nachkommastellen: int | None = Field(
        None, description="nur wenn der Vertrag eine Rundung vorschreibt"
    )
    fundstelle_definition: Fundstelle
    hinweise: list[Hinweis] = Field(
        default_factory=list,
        description="z. B. Rechtsfolge einer Planabweichung, Heilung, Fallen",
    )


class Margenstufe(BaseModel):
    kennzahl: str
    ueber: float | None = Field(None, description="Untergrenze exklusiv")
    bis_einschliesslich: float | None = None
    marge_prozent: float
    fundstelle: Fundstelle


class Vertrag(BaseModel):
    vertragsname: str
    hat_financial_covenants: bool
    begruendung: str
    begruendung_fundstelle: Fundstelle | None = None
    zwischengroessen: list[Zwischengroesse] = Field(default_factory=list)
    covenants: list[Covenant] = Field(default_factory=list)
    margenraster: list[Margenstufe] = Field(default_factory=list)


def iter_terme(v: Vertrag) -> Iterator[tuple[str, Term]]:
    """Alle Terme mit stabiler ID (für Zuordnung und Ergebnis)."""
    for g in v.zwischengroessen:
        for i, t in enumerate(g.terme):
            yield f"{g.name}/{i}", t
    for c in v.covenants:
        for teil in ("zaehler", "nenner"):
            for i, t in enumerate(getattr(c, teil)):
                yield f"{c.kennzahl}/{teil}/{i}", t


def iter_fundstellen(v: Vertrag) -> Iterator[Fundstelle]:
    if v.begruendung_fundstelle:
        yield v.begruendung_fundstelle
    for g in v.zwischengroessen:
        yield g.fundstelle
    for _, t in iter_terme(v):
        yield t.fundstelle
    for c in v.covenants:
        yield c.fundstelle_definition
        for g in c.grenzwerte:
            yield g.fundstelle
        for h in c.hinweise:
            yield h.fundstelle
    for m in v.margenraster:
        yield m.fundstelle


# --- Zuordnung Vertragsterm → Wirtschaftsplan ---------------------------------


class Quelle(BaseModel):
    blatt: str
    zeile: str
    spalte: str
    vorzeichen: Literal[1, -1] = 1
    uebernahme: Literal["wert", "betrag"] = Field(
        description="'betrag' = Absolutbetrag (Aufwand steht im Plan negativ), "
        "'wert' = Wert wie ausgewiesen"
    )


class TermZuordnung(BaseModel):
    term_id: str
    quellen: list[Quelle]
    nicht_im_plan: bool = Field(
        False, description="Position existiert im Plan nicht (wird mit 0 angesetzt)"
    )
    begruendung: str


class Zuordnung(BaseModel):
    zuordnungen: list[TermZuordnung]
