"""Phase 4: calc/covenants.py gegen die Handrechnung aus Phase 1 (docs/ANALYSE.md).

Teil A rechnet mit den Referenzdaten (Extraktion + Zuordnung) auf dem echten Wirtschaftsplan.
Teil B prüft die Rechenregeln isoliert mit synthetischen Plänen.
"""

from datetime import date
from decimal import Decimal

import pytest

from conftest import D, FIXTURES
from finn.calc.covenants import BerechnungsFehler, berechne_vertrag, runde
from finn.extraction.schema import (Covenant, Fundstelle, Grenzwert, Margenstufe, Quelle, Term,
                                    TermZuordnung, Vertrag, Zuordnung, Zwischengroesse)
from finn.plan.wirtschaftsplan import Planindex, Zelle, lade_plan

STICHTAG = date(2027, 12, 31)
REF = FIXTURES / "referenz"


# =============================================================================
# A. Handrechnung Phase 1 auf dem echten Wirtschaftsplan
# =============================================================================


@pytest.fixture(scope="module")
def plan():
    from finn.config import PROJEKT_ROOT

    return lade_plan((PROJEKT_ROOT / "data" / "Wirtschaftsplan_2027.xlsx").read_bytes())


def _rechne(plan, stem, mutiere=None):
    v = Vertrag.model_validate_json((REF / "extraktion" / f"{stem}.json").read_text())
    z = Zuordnung.model_validate_json((REF / "zuordnung" / f"{stem}.json").read_text())
    if mutiere:
        mutiere(v, z)
    return berechne_vertrag(f"{stem}.pdf", v, z, plan, STICHTAG)


def _cov(ve, kennzahl):
    return next(e for e in ve.covenants if e.kennzahl == kennzahl)


def _posten(posten, bezeichnung):
    for p in posten:
        if p.bezeichnung == bezeichnung:
            return p
        if p.unterposten and (t := _posten(p.unterposten, bezeichnung)):
            return t
    return None


def test_v1_sparkasse_keine_covenants(plan):
    ve = _rechne(plan, "Vertrag_1_Sparkasse_Investitionsdarlehen")
    assert ve.covenants == []


def test_v2_wirtschaftliche_ek_quote(plan):
    e = _cov(_rechne(plan, "Vertrag_2_Foerderbank_Foerderdarlehen"), "Wirtschaftliche Eigenkapitalquote")
    assert e.zaehler == D(107500)          # 96.100 + 50 % × 22.800
    assert e.nenner == D(313200)
    assert runde(e.wert, 2) == D("34.32")
    assert e.rundung is None and e.wert == e.wert_roh   # Vertrag schreibt keine Rundung vor
    assert e.grenzwert == D("27.5") and e.richtung == "min"
    assert runde(e.headroom, 2) == D("6.82")
    assert e.eingehalten
    sopo = _posten(e.zaehler_posten, "Sonderposten für Investitions- und Baukostenzuschüsse")
    assert sopo.basis == D(22800) and sopo.faktor == D("0.5") and sopo.wert == D(11400)
    assert [q.ref for q in sopo.quellen] == ["Bilanz!D23"]


def test_v3_dscr(plan):
    ve = _rechne(plan, "Vertrag_3_Landesbank_Investitionsdarlehen")
    e = _cov(ve, "Schuldendienstdeckungsgrad")
    assert ve.groessen["ebitda"].wert == D(40200)
    assert e.zaehler == D(37000)           # EBITDA − Ertragsteuern
    assert e.nenner == D(23680)            # 4.930 Zinsen + 18.750 planm. Tilgung
    assert e.wert_roh == D("1.5625")
    assert e.wert == D("1.56")             # kaufmännisch, 2 Stellen (Anlage 3 Abs. 6)
    assert e.headroom == D("0.26") and e.eingehalten
    zins = _posten(e.nenner_posten, "Zinsaufwand für Finanzverbindlichkeiten")
    assert [q.ref for q in zins.quellen] == ["Finanzierung!G15"]   # inkl. Gesellschafterdarlehen
    tilg = _posten(e.nenner_posten, "planmäßige Tilgungsleistungen auf Finanzverbindlichkeiten")
    assert [q.ref for q in tilg.quellen] == ["Finanzierung!D15"]   # ohne Sondertilgung E8


def test_v3_ebitda_vorzeichen_und_zellen(plan):
    ve = _rechne(plan, "Vertrag_3_Landesbank_Investitionsdarlehen")
    erwartet = {  # Bezeichnung: (Beitrag, Zelle, Zellwert)
        "Jahresüberschuss bzw. Jahresfehlbetrag": (10700, "GuV!D18", 10700),
        "Steuern vom Einkommen und vom Ertrag": (3200, "GuV!D17", -3200),
        "Zinsen und ähnliche Aufwendungen": (5100, "GuV!D13", -5100),
        "sonstige Zinsen und ähnliche Erträge": (-300, "GuV!D12", 300),
        "Abschreibungen auf immaterielle Vermögensgegenstände und Sachanlagen": (21500, "GuV!D9", -21500),
    }
    posten = {p.bezeichnung: p for p in ve.groessen["ebitda"].posten}
    for name, (beitrag, ref, roh) in erwartet.items():
        p = posten[name]
        assert p.wert == D(beitrag), name
        assert [(q.ref, q.roh) for q in p.quellen] == [(ref, D(roh))], name
    ao = next(p for p in posten.values() if p.bezeichnung.startswith("außerordentliche"))
    assert ao.nicht_im_plan and ao.wert == 0
    assert any("außerordentliche" in w for w in ve.warnungen)


def test_v4_ek_quote(plan):
    e = _cov(_rechne(plan, "Vertrag_4_Konsortialkredit"), "Eigenkapitalquote")
    assert e.zaehler == D(96100)           # ohne Sonderposten
    assert e.nenner == D(313200)
    assert runde(e.wert_roh, 4) == D("30.6833")
    assert e.wert == D("30.7")             # 1 Nachkommastelle (§ 14 Abs. 2)
    assert e.headroom == D("0.7") and e.eingehalten


def test_v4_dynamischer_verschuldungsgrad(plan):
    ve = _rechne(plan, "Vertrag_4_Konsortialkredit")
    e = _cov(ve, "Dynamischer Verschuldungsgrad")
    assert ve.groessen["nettofinanzverbindlichkeiten"].wert == D(135600)   # 148.200 − 12.600
    assert ve.groessen["ebitda"].wert == D(40200)
    assert e.wert == D("3.37") and e.richtung == "max"
    assert e.headroom == D("0.13") and e.eingehalten
    assert e.marge[0] == D("1.25")         # Margenraster > 3,00 (nur Info)


# --- Fallen aus Phase 1: falsche Definition → anderes Ergebnis -----------------


def test_falle_v4_mit_gesellschafterdarlehen_waere_bruch(plan):
    def inkl_gd(v, z):
        tz = next(t for t in z.zuordnungen if t.term_id == "Nettofinanzverbindlichkeiten/0")
        tz.quellen.append(Quelle(blatt="Bilanz", zeile=next(
            k for k in plan.blaetter["Bilanz"] if k.startswith("Verbindlichkeiten gegenüber Gesellschafter")),
            spalte="31.12.2027 (Plan)", uebernahme="wert"))

    e = _cov(_rechne(plan, "Vertrag_4_Konsortialkredit", inkl_gd), "Dynamischer Verschuldungsgrad")
    assert e.wert == D("3.57") and not e.eingehalten and e.headroom == D("-0.07")


def test_falle_v4_mit_sonderposten(plan):
    def mit_sopo(v, z):
        v.covenants[0].zaehler.append(Term(bezeichnung="Sonderposten", art="planposition", vorzeichen=1,
                                           fundstelle=v.covenants[0].zaehler[0].fundstelle))
        z.zuordnungen.append(TermZuordnung(term_id="Eigenkapitalquote/zaehler/1", begruendung="-", quellen=[
            Quelle(blatt="Bilanz", zeile="B. Sonderposten für Investitions- und Baukostenzuschüsse",
                   spalte="31.12.2027 (Plan)", uebernahme="wert")]))

    assert _cov(_rechne(plan, "Vertrag_4_Konsortialkredit", mit_sopo), "Eigenkapitalquote").wert == D("38.0")


def test_falle_v3_mit_sondertilgung(plan):
    def mit_st(v, z):
        tz = next(t for t in z.zuordnungen if t.term_id == "Schuldendienstdeckungsgrad/nenner/1")
        tz.quellen.append(Quelle(blatt="Finanzierung", zeile="Summe Darlehen gesamt",
                                 spalte="Sondertilgung 2027", uebernahme="wert"))

    assert _cov(_rechne(plan, "Vertrag_3_Landesbank_Investitionsdarlehen", mit_st),
                "Schuldendienstdeckungsgrad").wert == D("1.39")


def test_falle_v3_mit_aufzinsung(plan):
    def gesamt_zins(v, z):
        tz = next(t for t in z.zuordnungen if t.term_id == "Schuldendienstdeckungsgrad/nenner/0")
        tz.quellen = [Quelle(blatt="GuV", zeile="Zinsen und ähnliche Aufwendungen",
                             spalte="Plan 2027", uebernahme="betrag")]

    e = _cov(_rechne(plan, "Vertrag_3_Landesbank_Investitionsdarlehen", gesamt_zins), "Schuldendienstdeckungsgrad")
    assert e.nenner == D(23850) and e.wert == D("1.55")


def test_v3_zins_alternativ_aus_guv_minus_aufzinsung(plan):
    """Gleiches Ergebnis, wenn die Zuordnung GuV-Zinsen − Aufzinsung statt Darlehensspiegel wählt."""
    def guv(v, z):
        tz = next(t for t in z.zuordnungen if t.term_id == "Schuldendienstdeckungsgrad/nenner/0")
        tz.quellen = [
            Quelle(blatt="GuV", zeile="Zinsen und ähnliche Aufwendungen", spalte="Plan 2027", uebernahme="betrag"),
            Quelle(blatt="GuV", zeile=next(k for k in plan.blaetter["GuV"] if k.startswith("davon aus der Aufzinsung")),
                   spalte="Plan 2027", uebernahme="betrag", vorzeichen=-1),
        ]

    e = _cov(_rechne(plan, "Vertrag_3_Landesbank_Investitionsdarlehen", guv), "Schuldendienstdeckungsgrad")
    assert e.nenner == D(23680) and e.wert == D("1.56")


# =============================================================================
# B. Rechenregeln isoliert
# =============================================================================

F = Fundstelle(seite=1, paragraph="§ 1", zitat="x")


def _plan(**werte) -> Planindex:
    return Planindex({"P": {k: {"Plan": Zelle(D(v), f"P!{k}")} for k, v in werte.items()}})


def _t(name, v=1, art="planposition", faktor=1.0):
    return Term(bezeichnung=name, art=art, vorzeichen=v, faktor=faktor, fundstelle=F)


def _q(zeile, ueb="wert", v=1):
    return Quelle(blatt="P", zeile=zeile, spalte="Plan", uebernahme=ueb, vorzeichen=v)


def _cov_def(zaehler, nenner, grenz, richtung="min", einheit="faktor", rundung=None, grenzwerte=None):
    return Covenant(kennzahl="K", definition_wortlaut="-", einheit=einheit, zaehler=zaehler, nenner=nenner,
                    richtung=richtung, rundung_nachkommastellen=rundung, fundstelle_definition=F,
                    grenzwerte=grenzwerte or [Grenzwert(wert=grenz, fundstelle=F)])


def _einfach(z, n, grenz, **kw):
    """Kennzahl = Z / N mit Planzeilen Z und N."""
    v = Vertrag(vertragsname="T", hat_financial_covenants=True, begruendung="-",
                covenants=[_cov_def([_t("Z")], [_t("N")], grenz, **kw)])
    zu = Zuordnung(zuordnungen=[TermZuordnung(term_id="K/zaehler/0", quellen=[_q("Z")], begruendung="-"),
                                TermZuordnung(term_id="K/nenner/0", quellen=[_q("N")], begruendung="-")])
    return berechne_vertrag("t.pdf", v, zu, _plan(Z=z, N=n), STICHTAG).covenants[0]


@pytest.mark.parametrize("z,n,stellen,erwartet", [
    (15625, 10000, 2, "1.56"),   # DSCR Vertrag 3: 1,5625 → 1,56
    (16250, 10000, 2, "1.63"),   # 1,625 → 1,63 (Banker's Rounding ergäbe 1,62)
    (30650, 1000, 1, "30.7"),    # 30,65 → 30,7 (Banker's Rounding ergäbe 30,6)
    (33730, 10000, 2, "3.37"),
])
def test_kaufmaennische_rundung(z, n, stellen, erwartet):
    assert str(_einfach(z, n, 1.0, rundung=stellen).wert) == erwartet


def test_rundung_entscheidet_ueber_einhaltung():
    # 2,995 roh → gerundet 3,00 ≤ 3,00 → eingehalten; ohne Rundung verletzt
    assert _einfach(2995, 1000, 3.0, richtung="max", rundung=2).eingehalten
    assert not _einfach(3005, 1000, 3.0, richtung="max", rundung=2).eingehalten   # 3,005 → 3,01
    assert not _einfach(3001, 1000, 3.0, richtung="max").eingehalten              # ohne Rundungsregel


def test_grenzwert_genau_getroffen_ist_eingehalten():
    e = _einfach(13, 10, 1.30, rundung=2)
    assert e.wert == D("1.30") and e.headroom == 0 and e.eingehalten
    e = _einfach(35, 10, 3.50, richtung="max", rundung=2)
    assert e.headroom == 0 and e.eingehalten


def test_headroom_vorzeichen_min_und_max():
    assert _einfach(12, 10, 1.30, rundung=2).headroom == D("-0.10")            # min verletzt
    assert _einfach(40, 10, 3.50, richtung="max", rundung=2).headroom == D("-0.50")
    assert _einfach(30, 10, 3.50, richtung="max", rundung=2).headroom == D("0.50")


def test_prozent_einheit():
    e = _einfach(300, 1000, 27.5, einheit="prozent", rundung=1)
    assert e.wert == D("30.0") and e.headroom == D("2.5")


def test_nenner_null():
    with pytest.raises(BerechnungsFehler, match="Nenner"):
        _einfach(1, 0, 1.0)


def test_gestaffelte_grenzwerte():
    staffel = [Grenzwert(wert=4.0, gueltig_bis="2026-12-31", fundstelle=F),
               Grenzwert(wert=3.5, gueltig_ab="2027-01-01", gueltig_bis="2027-12-31", fundstelle=F),
               Grenzwert(wert=3.0, gueltig_ab="2028-01-01", fundstelle=F)]
    e = _einfach(36, 10, 0, richtung="max", grenzwerte=staffel)
    assert e.grenzwert == D("3.5") and not e.eingehalten


def test_staffel_luecke_oder_ueberlappung_ist_fehler():
    luecke = [Grenzwert(wert=4.0, gueltig_bis="2026-12-31", fundstelle=F)]
    with pytest.raises(BerechnungsFehler, match="0 Grenzwerte"):
        _einfach(1, 1, 0, grenzwerte=luecke)
    doppelt = [Grenzwert(wert=4.0, fundstelle=F), Grenzwert(wert=3.0, fundstelle=F)]
    with pytest.raises(BerechnungsFehler, match="2 Grenzwerte"):
        _einfach(1, 1, 0, grenzwerte=doppelt)
    with pytest.raises(BerechnungsFehler, match="ungültiges Datum"):
        _einfach(1, 1, 0, grenzwerte=[Grenzwert(wert=1, gueltig_ab="31.12.2027", fundstelle=F)])


def test_betrag_vs_wert_bei_negativem_jahresergebnis():
    """Jahresfehlbetrag (negativ, 'wert') bleibt negativ, Aufwand ('betrag') wird positiv addiert."""
    v = Vertrag(vertragsname="T", hat_financial_covenants=True, begruendung="-",
                zwischengroessen=[Zwischengroesse(name="EBITDA", fundstelle=F,
                                                  terme=[_t("JÜ"), _t("Steuern"), _t("AfA")])],
                covenants=[_cov_def([_t("EBITDA", art="zwischengroesse")], [_t("N")], 1.0)])
    zu = Zuordnung(zuordnungen=[
        TermZuordnung(term_id="EBITDA/0", quellen=[_q("JUE")], begruendung="-"),
        TermZuordnung(term_id="EBITDA/1", quellen=[_q("ST", "betrag")], begruendung="-"),
        TermZuordnung(term_id="EBITDA/2", quellen=[_q("AFA", "betrag")], begruendung="-"),
        TermZuordnung(term_id="K/nenner/0", quellen=[_q("N")], begruendung="-"),
    ])
    ve = berechne_vertrag("t.pdf", v, zu, _plan(JUE=-500, ST=-100, AFA=-2000, N=1000), STICHTAG)
    assert ve.groessen["ebitda"].wert == D(1600)       # −500 + 100 + 2.000


def test_faktor_und_abzug():
    v = Vertrag(vertragsname="T", hat_financial_covenants=True, begruendung="-",
                covenants=[_cov_def([_t("EK"), _t("SoPo", faktor=0.5), _t("Ausst", v=-1)], [_t("BS")], 0,
                                    einheit="prozent")])
    zu = Zuordnung(zuordnungen=[
        TermZuordnung(term_id="K/zaehler/0", quellen=[_q("EK")], begruendung="-"),
        TermZuordnung(term_id="K/zaehler/1", quellen=[_q("SP")], begruendung="-"),
        TermZuordnung(term_id="K/zaehler/2", quellen=[_q("AE")], begruendung="-"),
        TermZuordnung(term_id="K/nenner/0", quellen=[_q("BS")], begruendung="-"),
    ])
    e = berechne_vertrag("t.pdf", v, zu, _plan(EK=1000, SP=301, AE=50, BS=4000), STICHTAG).covenants[0]
    assert e.zaehler == D("1100.5")                   # 1.000 + 150,5 − 50
    assert e.wert == D("1100.5") / 4000 * 100


def test_zwischengroesse_fehlend_und_zirkulaer():
    zirk = Vertrag(vertragsname="T", hat_financial_covenants=True, begruendung="-",
                   zwischengroessen=[Zwischengroesse(name="A", fundstelle=F, terme=[_t("B", art="zwischengroesse")]),
                                     Zwischengroesse(name="B", fundstelle=F, terme=[_t("A", art="zwischengroesse")])],
                   covenants=[_cov_def([_t("A", art="zwischengroesse")], [_t("A", art="zwischengroesse")], 1)])
    with pytest.raises(BerechnungsFehler, match="Zirkulär"):
        berechne_vertrag("t.pdf", zirk, Zuordnung(zuordnungen=[]), _plan(), STICHTAG)
    fehlt = Vertrag(vertragsname="T", hat_financial_covenants=True, begruendung="-",
                    covenants=[_cov_def([_t("X", art="zwischengroesse")], [_t("N")], 1)])
    with pytest.raises(BerechnungsFehler, match="nicht definiert"):
        berechne_vertrag("t.pdf", fehlt, Zuordnung(zuordnungen=[]), _plan(), STICHTAG)


def test_fehlende_zuordnung_ist_fehler():
    v = Vertrag(vertragsname="T", hat_financial_covenants=True, begruendung="-",
                covenants=[_cov_def([_t("Z")], [_t("N")], 1)])
    with pytest.raises(BerechnungsFehler, match="Keine Planzuordnung"):
        berechne_vertrag("t.pdf", v, Zuordnung(zuordnungen=[]), _plan(Z=1, N=1), STICHTAG)


@pytest.mark.parametrize("dvg,marge", [("2.50", "0.95"), ("2.51", "1.10"), ("3.00", "1.10"), ("3.01", "1.25")])
def test_margenraster_grenzen(dvg, marge):
    raster = [Margenstufe(kennzahl="K", bis_einschliesslich=2.5, marge_prozent=0.95, fundstelle=F),
              Margenstufe(kennzahl="K", ueber=2.5, bis_einschliesslich=3.0, marge_prozent=1.10, fundstelle=F),
              Margenstufe(kennzahl="K", ueber=3.0, marge_prozent=1.25, fundstelle=F)]
    v = Vertrag(vertragsname="T", hat_financial_covenants=True, begruendung="-", margenraster=raster,
                covenants=[_cov_def([_t("Z")], [_t("N")], 3.5, richtung="max", rundung=2)])
    zu = Zuordnung(zuordnungen=[TermZuordnung(term_id="K/zaehler/0", quellen=[_q("Z")], begruendung="-"),
                                TermZuordnung(term_id="K/nenner/0", quellen=[_q("N")], begruendung="-")])
    e = berechne_vertrag("t.pdf", v, zu, _plan(Z=D(dvg) * 100, N=100), STICHTAG).covenants[0]
    assert e.marge[0] == D(marge)


def test_ohne_covenants_keine_berechnung():
    v = Vertrag(vertragsname="T", hat_financial_covenants=False, begruendung="-",
                covenants=[_cov_def([_t("Z")], [_t("N")], 1)])   # widersprüchlich → Flag gewinnt
    assert berechne_vertrag("t.pdf", v, Zuordnung(zuordnungen=[]), _plan(), STICHTAG).covenants == []


def test_runde_ist_decimal_half_up():
    assert runde(Decimal("2.345"), 2) == Decimal("2.35")
    assert runde(Decimal("-2.345"), 2) == Decimal("-2.35")
