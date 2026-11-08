from finn.pipeline import pruefe
from finn.report import summary


def test_fallback_zahlen_sind_belegt(auftrag, offline, cfg):
    erg = pruefe(auftrag, offline, cfg).ergebnisse
    text = summary.fallback(erg, cfg.stichtag)
    erlaubt = summary.erlaubte_zahlen(erg, cfg.stichtag)
    # Vertragsnummer im Namen ist keine Ergebniszahl → nur Zahlen außerhalb der Namen prüfen
    for ve in erg:
        text = text.replace(ve.vertrag.vertragsname, "")
    assert summary.pruefe_zahlen(text, erlaubt, cfg.stichtag) == []


def test_erfundene_zahl_wird_erkannt(auftrag, offline, cfg):
    erg = pruefe(auftrag, offline, cfg).ergebnisse
    erlaubt = summary.erlaubte_zahlen(erg, cfg.stichtag)
    ok = "Alle 4 Covenants sind eingehalten; der DSCR liegt bei 1,56 (Grenzwert 1,30), EBITDA 40.200 T€."
    assert summary.pruefe_zahlen(ok, erlaubt, cfg.stichtag) == []
    schlecht = "Der DSCR liegt bei 1,62 zum 30.06.2027."
    assert set(summary.pruefe_zahlen(schlecht, erlaubt, cfg.stichtag)) == {"1,62", "30.06.2027"}
