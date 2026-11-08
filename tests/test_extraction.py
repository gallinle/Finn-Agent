"""Phase 3: Verifikation der Zitate, Zuordnungsprüfung, Cache-Extraktion vs. Referenz."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from finn.config import PROJEKT_ROOT
from finn.extraction import mapping, verify
from finn.extraction.contracts import ClaudeDienste, pdf_hash
from finn.extraction.schema import Vertrag
from finn.pipeline import pruefe
from finn.plan.wirtschaftsplan import lade_plan

VERTRAEGE = PROJEKT_ROOT / "data" / "vertraege"
REFERENZ = Path(__file__).parent / "fixtures" / "referenz" / "extraktion"
CACHE = PROJEKT_ROOT / "cache"


def _pdf(name):
    return (VERTRAEGE / f"{name}.pdf").read_bytes()


# --- verify.py ---------------------------------------------------------------


@pytest.fixture(scope="module")
def seiten_v3():
    return verify.seitentexte(_pdf("Vertrag_3_Landesbank_Investitionsdarlehen"))


def test_zitat_ueber_zeilenumbrueche_gefunden(seiten_v3):
    # im PDF steht jedes Wort dieses Satzes in einer eigenen Zeile
    z = "den im Berechnungszeitraum fälligen planmäßigen Tilgungsleistungen auf Finanzverbindlichkeiten"
    assert verify.pruefe_zitat(seiten_v3, 13, z).gefunden


def test_zitat_falsche_seite(seiten_v3):
    p = verify.pruefe_zitat(seiten_v3, 6, "einen Schuldendienstdeckungsgrad von mindestens 1,30 einzuhalten")
    assert not p.gefunden and p.gefunden_auf == 5


def test_erfundenes_zitat(seiten_v3):
    p = verify.pruefe_zitat(seiten_v3, 5, "einen Schuldendienstdeckungsgrad von mindestens 1,20 einzuhalten")
    assert not p.gefunden and p.gefunden_auf is None


def test_typografische_anfuehrungszeichen(seiten_v3):
    assert verify.pruefe_zitat(seiten_v3, 1, '"Tranche A" bezeichnet den Teilbetrag des Darlehens').gefunden


@pytest.mark.parametrize("quelle", [REFERENZ, CACHE / "extraktion"])
def test_alle_zitate_verifiziert(quelle):
    for pdf in sorted(VERTRAEGE.glob("*.pdf")):
        daten = pdf.read_bytes()
        datei = quelle / (f"{pdf.stem}.json" if quelle == REFERENZ else f"{pdf_hash(daten)}.json")
        if not datei.exists():
            pytest.skip(f"kein Cache für {pdf.name}")
        txt = datei.read_text(encoding="utf-8")
        v = (Vertrag.model_validate_json(txt) if quelle == REFERENZ
             else Vertrag.model_validate(__import__("json").loads(txt)["vertrag"]))
        fehlend = [p for p in verify.pruefe_vertrag(daten, v) if not p.gefunden]
        assert not fehlend, (pdf.name, fehlend)
        assert verify.pruefe_grenzwerte(v) == []


def test_grenzwert_nicht_im_zitat():
    v = Vertrag.model_validate_json((REFERENZ / "Vertrag_3_Landesbank_Investitionsdarlehen.json").read_text(encoding="utf-8"))
    v.covenants[0].grenzwerte[0].wert = 1.5
    assert len(verify.pruefe_grenzwerte(v)) == 1


# --- mapping.py (Validierung ohne API) ---------------------------------------


@pytest.fixture(scope="module")
def plan():
    return lade_plan((PROJEKT_ROOT / "data" / "Wirtschaftsplan_2027.xlsx").read_bytes())


def _roh(*zuordnungen):
    return NS(zuordnungen=[NS(term_id=t, quellen=[NS(zeile=z, spalte=s, vorzeichen=1, uebernahme="wert")
                                                  for z, s in qs],
                              nicht_im_plan=not qs, begruendung="-") for t, qs in zuordnungen])


def test_schema_erlaubt_nur_vorhandene_zeilen(plan):
    schema = mapping._schema(plan, ["X/0"])
    ok = {"term_id": "X/0", "begruendung": "-",
          "quellen": [{"zeile": "Bilanz › A. Eigenkapital", "spalte": "31.12.2027 (Plan)", "uebernahme": "wert"}]}
    schema.model_validate({"zuordnungen": [ok]})
    falsch = {**ok, "quellen": [{**ok["quellen"][0], "zeile": "Bilanz › Eigenkapital (erfunden)"}]}
    with pytest.raises(Exception):
        schema.model_validate({"zuordnungen": [falsch]})


def test_pruefe_lehnt_ist_spalte_und_luecken_ab(plan):
    roh = _roh(("A/0", [("GuV › Jahresüberschuss", "Ist 2025")]))
    _, fehler = mapping.pruefe(roh, plan, ["A/0", "A/1"], 2027)
    assert any("Planjahr" in f for f in fehler)
    assert any("A/1" in f for f in fehler)


def test_pruefe_lehnt_spalte_anderen_blatts_ab(plan):
    roh = _roh(("A/0", [("GuV › Jahresüberschuss", "31.12.2027 (Plan)")]))
    _, fehler = mapping.pruefe(roh, plan, ["A/0"], 2027)
    assert any("existiert nicht" in f for f in fehler)


def test_pruefe_ok(plan):
    roh = _roh(("A/0", [("Finanzierung › Summe Darlehen gesamt", "Zinsaufwand 2027")]), ("A/1", []))
    z, fehler = mapping.pruefe(roh, plan, ["A/0", "A/1"], 2027)
    assert fehler == []
    assert z.zuordnungen[0].quellen[0].blatt == "Finanzierung"
    assert z.zuordnungen[1].nicht_im_plan


def test_katalog_enthaelt_erlaeuterungen(plan):
    t = mapping.katalog_text(plan, 2027)
    assert "qualifiziertem Rangrücktritt" in t and "Finanzierung › Summe Darlehen gesamt" in t


# --- Cache: reproduzierbarer Lauf mit der echten Claude-Extraktion ------------


@pytest.fixture
def cache_dienste(cfg):
    if not any((CACHE / "extraktion").glob("*.json")):
        pytest.skip("kein Extraktions-Cache vorhanden")
    return ClaudeDienste(replace(cfg, cache_dir=CACHE), nur_cache=True)


def test_cache_lauf_entspricht_phase1(auftrag, cache_dienste, cfg):
    lauf = pruefe(auftrag, cache_dienste, replace(cfg, cache_dir=CACHE))
    werte = {(v.datei, e.kennzahl.split(" (")[0]): str(e.wert)
             for v in lauf.ergebnisse for e in v.covenants}
    assert {k[0] for k in werte} == {"Vertrag_2_Foerderbank_Foerderdarlehen.pdf",
                                     "Vertrag_3_Landesbank_Investitionsdarlehen.pdf",
                                     "Vertrag_4_Konsortialkredit.pdf"}
    assert werte[("Vertrag_3_Landesbank_Investitionsdarlehen.pdf", "Schuldendienstdeckungsgrad")] == "1.56"
    assert werte[("Vertrag_4_Konsortialkredit.pdf", "Eigenkapitalquote")] == "30.7"
    assert werte[("Vertrag_4_Konsortialkredit.pdf", "Dynamischer Verschuldungsgrad")] == "3.37"
    v2 = next(e for v in lauf.ergebnisse for e in v.covenants if v.datei.startswith("Vertrag_2"))
    assert round(v2.wert, 2) == round(v2.zaehler / v2.nenner * 100, 2)
    assert f"{v2.wert:.2f}" == "34.32"
    assert all(e.eingehalten for v in lauf.ergebnisse for e in v.covenants)
    assert "Zitat nicht verifiziert" not in lauf.antwort.html


def test_cache_extraktion_struktur_wie_referenz(cache_dienste):
    for pdf in sorted(VERTRAEGE.glob("*.pdf")):
        ist = cache_dienste.extrahiere(pdf.read_bytes(), pdf.name)
        soll = Vertrag.model_validate_json((REFERENZ / f"{pdf.stem}.json").read_text(encoding="utf-8"))
        assert ist.hat_financial_covenants == soll.hat_financial_covenants, pdf.name
        assert len(ist.covenants) == len(soll.covenants), pdf.name
        for i, s in zip(ist.covenants, soll.covenants):
            assert (i.einheit, i.richtung, i.rundung_nachkommastellen) == \
                   (s.einheit, s.richtung, s.rundung_nachkommastellen), (pdf.name, s.kennzahl)
            assert [g.wert for g in i.grenzwerte] == [g.wert for g in s.grenzwerte]
            assert i.grenzwerte[0].fundstelle.seite == s.grenzwerte[0].fundstelle.seite


def test_nur_cache_ruft_keine_api(cfg, tmp_path):
    d = ClaudeDienste(replace(cfg, cache_dir=tmp_path), nur_cache=True)
    with pytest.raises(RuntimeError, match="nur_cache"):
        d.extrahiere(b"%PDF-unbekannt", "x.pdf")

