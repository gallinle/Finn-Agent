"""Deutsche Zahlenformatierung (nur Darstellung, keine Berechnung von Kennzahlen)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def zahl(x: Decimal, stellen: int = 0, vorzeichen: bool = False) -> str:
    q = x.quantize(Decimal(1).scaleb(-stellen), rounding=ROUND_HALF_UP)
    s = f"{abs(q):,.{stellen}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if q < 0:
        return "−" + s
    return ("+" + s) if vorzeichen else s


def betrag(x: Decimal) -> str:
    """T€-Betrag; Nachkommastelle nur wenn nötig (z. B. 50 % eines ungeraden Werts)."""
    stellen = 0 if x == x.to_integral_value() else 1
    return zahl(x, stellen)


def anzeige_stellen(rundung: int | None) -> int:
    return rundung if rundung is not None else 2


def kennzahl(x: Decimal, einheit: str, rundung: int | None) -> str:
    s = zahl(x, anzeige_stellen(rundung))
    return f"{s} %" if einheit == "prozent" else s


def grenzwert(x: Decimal, einheit: str, richtung: str, rundung: int | None) -> str:
    natuerlich = max(0, -x.normalize().as_tuple().exponent)
    stellen = max(natuerlich, 1, rundung or 0)
    op = "≥" if richtung == "min" else "≤"
    s = zahl(x, stellen)
    return f"{op} {s} %" if einheit == "prozent" else f"{op} {s}"


def headroom(x: Decimal, einheit: str, rundung: int | None) -> str:
    s = zahl(x, anzeige_stellen(rundung), vorzeichen=True)
    return f"{s} Pp" if einheit == "prozent" else s
