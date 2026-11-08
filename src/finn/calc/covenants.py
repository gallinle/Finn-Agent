"""Deterministische Berechnung der Covenants. Hier – und nur hier – wird gerechnet."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from finn.extraction.schema import Covenant, Fundstelle, Term, Vertrag, Zuordnung
from finn.plan.wirtschaftsplan import Planindex


class BerechnungsFehler(Exception):
    pass


@dataclass
class Quellwert:
    ref: str  # Blatt!Zelle
    zeile: str
    roh: Decimal  # Wert in der Zelle
    beitrag: Decimal  # nach vorzeichen/uebernahme


@dataclass
class Posten:
    term_id: str
    bezeichnung: str
    vorzeichen: int
    faktor: Decimal
    wert: Decimal  # Beitrag zur Summe (inkl. Vorzeichen und Faktor)
    basis: Decimal  # Wert der Position vor Vorzeichen/Faktor
    fundstelle: Fundstelle
    quellen: list[Quellwert] = field(default_factory=list)
    zwischengroesse: str | None = None
    unterposten: list["Posten"] = field(default_factory=list)
    hinweis: str | None = None
    nicht_im_plan: bool = False


@dataclass
class Groesse:
    name: str
    wert: Decimal
    posten: list[Posten]
    fundstelle: Fundstelle


@dataclass
class Spielraum:
    """Änderung des Treibers (T€), bei der der Grenzwert genau erreicht wäre.

    Negativ = Rückgang bis zum Grenzwert; übrige Planwerte unverändert, ohne Rundungseffekt.
    """

    treiber: str
    aenderung: Decimal


@dataclass
class CovenantErgebnis:
    vertrag: str
    kennzahl: str
    einheit: str
    richtung: str
    wert_roh: Decimal
    wert: Decimal  # nach vertraglicher Rundung (sonst = roh)
    grenzwert: Decimal
    headroom: Decimal
    eingehalten: bool
    zaehler: Decimal
    nenner: Decimal
    zaehler_posten: list[Posten]
    nenner_posten: list[Posten]
    covenant: Covenant
    grenzwert_fundstelle: Fundstelle
    rundung: int | None
    marge: tuple[Decimal, Fundstelle] | None = None
    spielraum: Spielraum | None = None


@dataclass
class VertragsErgebnis:
    datei: str
    vertrag: Vertrag | None
    covenants: list[CovenantErgebnis]
    groessen: dict[str, Groesse]
    warnungen: list[str] = field(default_factory=list)
    fehler: str | None = None  # Prüfung dieses Vertrags nicht möglich

    @property
    def name(self) -> str:
        return self.vertrag.vertragsname if self.vertrag else self.datei

    @classmethod
    def fehlgeschlagen(cls, datei: str, vertrag: Vertrag | None, grund: str) -> "VertragsErgebnis":
        return cls(datei, vertrag, [], {}, [], grund)


def _d(x: float | int | str) -> Decimal:
    return Decimal(str(x))


def runde(x: Decimal, stellen: int) -> Decimal:
    return x.quantize(Decimal(1).scaleb(-stellen), rounding=ROUND_HALF_UP)


def _datum(s: str, c: Covenant) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise BerechnungsFehler(f"{c.kennzahl}: ungültiges Datum '{s}' in Grenzwert-Staffel") from None


def _grenzwert(c: Covenant, stichtag: date):
    passend = [
        g
        for g in c.grenzwerte
        if (g.gueltig_ab is None or _datum(g.gueltig_ab, c) <= stichtag)
        and (g.gueltig_bis is None or stichtag <= _datum(g.gueltig_bis, c))
    ]
    if len(passend) != 1:
        raise BerechnungsFehler(
            f"{c.kennzahl}: {len(passend)} Grenzwerte gelten zum {stichtag:%d.%m.%Y}"
        )
    return passend[0]


class _Rechner:
    def __init__(self, v: Vertrag, z: Zuordnung, plan: Planindex):
        self.v = v
        self.plan = plan
        self.zuordnung = {t.term_id: t for t in z.zuordnungen}
        self.groessen: dict[str, Groesse] = {}
        self._in_arbeit: set[str] = set()
        self.warnungen: list[str] = []

    def groesse(self, name: str) -> Groesse:
        key = name.strip().casefold()
        if key in self.groessen:
            return self.groessen[key]
        defn = next(
            (g for g in self.v.zwischengroessen if g.name.strip().casefold() == key), None
        )
        if defn is None:
            raise BerechnungsFehler(f"Zwischengröße '{name}' ist nicht definiert")
        if key in self._in_arbeit:
            raise BerechnungsFehler(f"Zirkuläre Definition bei '{name}'")
        self._in_arbeit.add(key)
        posten = [self.posten(f"{defn.name}/{i}", t) for i, t in enumerate(defn.terme)]
        self._in_arbeit.discard(key)
        g = Groesse(defn.name, sum((p.wert for p in posten), Decimal(0)), posten, defn.fundstelle)
        self.groessen[key] = g
        return g

    def posten(self, term_id: str, t: Term) -> Posten:
        faktor = _d(t.faktor)
        p = Posten(term_id, t.bezeichnung, t.vorzeichen, faktor, Decimal(0), Decimal(0),
                   t.fundstelle, hinweis=t.hinweis)
        if t.art == "zwischengroesse":
            g = self.groesse(t.bezeichnung)
            p.zwischengroesse = g.name
            p.unterposten = g.posten
            p.basis = g.wert
        else:
            tz = self.zuordnung.get(term_id)
            if tz is None:
                raise BerechnungsFehler(f"Keine Planzuordnung für '{t.bezeichnung}' ({term_id})")
            if tz.nicht_im_plan or not tz.quellen:
                p.nicht_im_plan = True
                self.warnungen.append(
                    f"„{t.bezeichnung}“ ist im Wirtschaftsplan nicht ausgewiesen und wird "
                    f"mit 0 angesetzt ({tz.begruendung})."
                )
            for q in tz.quellen:
                zelle = self.plan.get(q.blatt, q.zeile, q.spalte)
                roh = zelle.wert
                beitrag = q.vorzeichen * (abs(roh) if q.uebernahme == "betrag" else roh)
                p.quellen.append(Quellwert(zelle.ref, q.zeile, roh, beitrag))
                p.basis += beitrag
        p.wert = t.vorzeichen * faktor * p.basis
        return p


def berechne_covenant(
    c: Covenant, r: _Rechner, stichtag: date, vertragsname: str
) -> CovenantErgebnis:
    zp = [r.posten(f"{c.kennzahl}/zaehler/{i}", t) for i, t in enumerate(c.zaehler)]
    np_ = [r.posten(f"{c.kennzahl}/nenner/{i}", t) for i, t in enumerate(c.nenner)]
    zaehler = sum((p.wert for p in zp), Decimal(0))
    nenner = sum((p.wert for p in np_), Decimal(0))
    if nenner == 0:
        raise BerechnungsFehler(f"{c.kennzahl}: Nenner ist 0")
    roh = zaehler / nenner * (100 if c.einheit == "prozent" else 1)
    wert = runde(roh, c.rundung_nachkommastellen) if c.rundung_nachkommastellen is not None else roh
    gw = _grenzwert(c, stichtag)
    grenz = _d(gw.wert)
    headroom = wert - grenz if c.richtung == "min" else grenz - wert
    return CovenantErgebnis(
        vertrag=vertragsname, kennzahl=c.kennzahl, einheit=c.einheit, richtung=c.richtung,
        wert_roh=roh, wert=wert, grenzwert=grenz, headroom=headroom,
        eingehalten=headroom >= 0, zaehler=zaehler, nenner=nenner,
        zaehler_posten=zp, nenner_posten=np_, covenant=c,
        grenzwert_fundstelle=gw.fundstelle, rundung=c.rundung_nachkommastellen,
    )


def _koeffizient(posten: list[Posten], ist_treiber) -> Decimal:
    """Wie stark geht der Treiber (rekursiv über Zwischengrößen) in die Summe ein?"""
    k = Decimal(0)
    for p in posten:
        if ist_treiber(p):
            k += p.vorzeichen * p.faktor
        elif p.unterposten:
            k += p.vorzeichen * p.faktor * _koeffizient(p.unterposten, ist_treiber)
    return k


def _kurzname(name: str) -> str:
    while True:
        neu = re.sub(r"\s*\([^()]*\)\s*$", "", name).strip()
        if neu == name or not neu:
            return name
        name = neu


def berechne_spielraum(e: CovenantErgebnis) -> Spielraum | None:
    """Löst (Z + a·d) / (N + b·d) · k = Grenzwert nach d auf (a, b = Gewicht des Treibers)."""
    def ist_ebitda(p: Posten) -> bool:
        return (p.zwischengroesse or "").strip().casefold() == "ebitda"

    alle = e.zaehler_posten + e.nenner_posten
    if _koeffizient(alle, ist_ebitda) != 0:
        ist_treiber, name = ist_ebitda, "EBITDA"
    elif e.zaehler_posten:
        erster = e.zaehler_posten[0]
        ist_treiber, name = (lambda p: p is erster), _kurzname(erster.bezeichnung)
    else:
        return None
    a = _koeffizient(e.zaehler_posten, ist_treiber)
    b = _koeffizient(e.nenner_posten, ist_treiber)
    grenze = e.grenzwert / (100 if e.einheit == "prozent" else 1)
    nenner = a - grenze * b
    if nenner == 0:
        return None
    return Spielraum(name, (grenze * e.nenner - e.zaehler) / nenner)


def _marge(v: Vertrag, e: CovenantErgebnis):
    for m in v.margenraster:
        if m.kennzahl.strip().casefold() != e.kennzahl.strip().casefold():
            continue
        if (m.ueber is None or e.wert > _d(m.ueber)) and (
            m.bis_einschliesslich is None or e.wert <= _d(m.bis_einschliesslich)
        ):
            return _d(m.marge_prozent), m.fundstelle
    return None


def berechne_vertrag(
    datei: str, v: Vertrag, z: Zuordnung, plan: Planindex, stichtag: date
) -> VertragsErgebnis:
    r = _Rechner(v, z, plan)
    ergebnisse = []
    if v.hat_financial_covenants:
        for c in v.covenants:
            e = berechne_covenant(c, r, stichtag, v.vertragsname)
            e.marge = _marge(v, e)
            e.spielraum = berechne_spielraum(e)
            ergebnisse.append(e)
    return VertragsErgebnis(datei, v, ergebnisse, r.groessen, r.warnungen)
