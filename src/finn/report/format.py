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


# --- Formel und Spielraum (reine Darstellung der berechneten Struktur) ---------


def _kurz(name: str) -> str:
    from finn.calc.covenants import _kurzname

    return _kurzname(name)


def _summe(posten) -> str:
    teile = []
    for i, p in enumerate(posten):
        name = _kurz(p.zwischengroesse or p.bezeichnung)
        if p.faktor != 1:
            name = f"{zahl(p.faktor * 100, 0)} % × {name}"
        if i == 0:
            teile.append(("−" if p.vorzeichen < 0 else "") + name)
        else:
            teile.append(("− " if p.vorzeichen < 0 else "+ ") + name)
    return " ".join(teile)


def _klammer(posten) -> str:
    s = _summe(posten)
    return f"({s})" if len(posten) > 1 else s


def formel(e) -> str:
    """z. B. 'Schuldendienstdeckungsgrad = (EBITDA − Ertragsteuern) / Schuldendienst'."""
    f = f"{_kurz(e.kennzahl)} = {_klammer(e.zaehler_posten)} / {_klammer(e.nenner_posten)}"
    return f + " (in %)" if e.einheit == "prozent" else f


def formeln_zwischengroessen(e) -> list[str]:
    """Formeln der verwendeten Zwischengrößen, z. B. 'EBITDA = Jahresüberschuss + …'."""
    out, gesehen = [], set()

    def besuche(posten):
        for p in posten:
            if p.zwischengroesse and p.zwischengroesse not in gesehen:
                gesehen.add(p.zwischengroesse)
                out.append(f"{_kurz(p.zwischengroesse)} = {_summe(p.unterposten)}")
                besuche(p.unterposten)

    besuche(e.zaehler_posten + e.nenner_posten)
    return out


def spielraum(sr) -> str:
    """z. B. 'EBITDA −1.457 T€ (rd. 1,5 Mio. €)'."""
    if sr is None:
        return "–"
    return f"{sr.treiber} {zahl(sr.aenderung, 0, vorzeichen=True)} T€ (rd. {zahl(abs(sr.aenderung) / 1000, 1)} Mio. €)"


def spielraum_satz(sr) -> str:
    """z. B. 'bei einem Rückgang von EBITDA um 1.457 T€ (rd. 1,5 Mio. €)'."""
    richtung = "Rückgang" if sr.aenderung < 0 else "Anstieg"
    return (f"bei einem {richtung} von {sr.treiber} um {zahl(abs(sr.aenderung), 0)} T€ "
            f"(rd. {zahl(abs(sr.aenderung) / 1000, 1)} Mio. €)")
