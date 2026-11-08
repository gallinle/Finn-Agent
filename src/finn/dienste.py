"""Schnittstelle zu den LLM-Schritten (Lesen, Zuordnen, Formulieren).

Die Pipeline kennt nur dieses Protokoll. `OfflineDienste` liefert Referenzdaten aus
Dateien (Tests/Demo ohne API), die Claude-Implementierung liegt in finn.extraction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from finn.calc.covenants import VertragsErgebnis
from finn.extraction.schema import Vertrag, Zuordnung
from finn.plan.wirtschaftsplan import Planindex


class Dienste(Protocol):
    def extrahiere(self, pdf: bytes, datei: str) -> Vertrag: ...

    def ordne_zu(self, vertrag: Vertrag, plan: Planindex, datei: str) -> Zuordnung: ...

    def fasse_zusammen(self, ergebnisse: list[VertragsErgebnis], fakten: list[dict]) -> str | None:
        """None → deterministische Zusammenfassung verwenden."""
        ...


class OfflineDienste:
    """Liest Extraktion/Zuordnung aus <basis>/extraktion|zuordnung/<pdf-stem>.json."""

    def __init__(self, basis: Path):
        self.basis = basis

    def _lade(self, art: str, datei: str) -> str:
        p = self.basis / art / f"{Path(datei).stem}.json"
        return p.read_text(encoding="utf-8")

    def extrahiere(self, pdf: bytes, datei: str) -> Vertrag:
        return Vertrag.model_validate_json(self._lade("extraktion", datei))

    def ordne_zu(self, vertrag: Vertrag, plan: Planindex, datei: str) -> Zuordnung:
        return Zuordnung.model_validate(json.loads(self._lade("zuordnung", datei)))

    def fasse_zusammen(self, ergebnisse, fakten) -> str | None:
        return None
