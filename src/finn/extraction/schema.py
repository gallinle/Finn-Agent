# extraction/schema.py
from pydantic import BaseModel
from typing import Literal

class Fundstelle(BaseModel):
    seite: int
    paragraph: str          # z. B. "§ 12 Abs. 2" oder "Anlage 3"
    zitat: str              # wörtlich, wird in verify.py geprüft

class Term(BaseModel):
    position: str           # z. B. "Abschreibungen", "liquide Mittel"
    vorzeichen: Literal[1, -1]

class Covenant(BaseModel):
    kennzahl: str           # z. B. "Nettoverschuldung / EBITDA"
    definition_wortlaut: str
    zaehler: list[Term]
    nenner: list[Term]
    grenzwert: float
    richtung: Literal["max", "min"]
    stichtag_regel: str
    fundstelle_definition: Fundstelle
    fundstelle_grenzwert: Fundstelle

class Vertrag(BaseModel):
    hat_financial_covenants: bool
    begruendung: str
    covenants: list[Covenant]