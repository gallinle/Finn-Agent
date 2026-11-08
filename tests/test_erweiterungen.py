"""Ergänzungen nach dem Abgleich mit dem Aufgabenblatt:
winmail.dat (TNEF), Spam-Ordner, Spielraum bis zum Grenzwert, Formel je Covenant.
"""

import struct
from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from types import SimpleNamespace as NS

import pytest
from tnefparse import TNEF

from conftest import D, FIXTURES
from finn.calc.covenants import berechne_vertrag
from finn.extraction.schema import Vertrag, Zuordnung
from finn.mail.inbox import Postfach, UidSpeicher
from finn.pipeline import anhaenge, pruefe, sieht_wie_auftrag
from finn.plan.wirtschaftsplan import lade_plan
from finn.report import format as fmt
from finn.report import summary
from test_mail import _Msg

REF = FIXTURES / "referenz"


# --- winmail.dat (TNEF) ------------------------------------------------------


def _tnef(dateien: list[tuple[str, bytes]]) -> bytes:
    def attr(level, name, typ, data):
        return struct.pack("<BHHI", level, name, typ, len(data)) + data + struct.pack("<H", sum(data) & 0xFFFF)

    out = struct.pack("<IH", TNEF.TNEF_SIGNATURE, 1) + attr(1, 0x9006, 0x0008, struct.pack("<I", 0x00010000))
    for name, daten in dateien:
        out += attr(2, TNEF.ATTATTACHRENDDATA, 0x0006, b"\x01\x00" + b"\xff" * 4 + b"\x00" * 8)
        out += attr(2, TNEF.ATTATTACHTITLE, 0x0001, name.encode("cp1252") + b"\x00")
        out += attr(2, TNEF.ATTATTACHDATA, 0x0006, daten)
    return out


def _mail(anhaenge_: list[tuple[str, bytes, str]], uid="1", von="k.beispiel@firma.example"):
    m = EmailMessage()
    m["From"] = von
    m["Subject"] = "Covenant-Prüfung Wirtschaftsplan 2027"
    m["Message-ID"] = f"<w{uid}@firma.example>"
    m.set_content("bitte prüfen")
    for name, daten, ctype in anhaenge_:
        maintype, subtype = ctype.split("/")
        m.add_attachment(daten, maintype=maintype, subtype=subtype, filename=name)
    msg = _Msg.from_bytes(bytes(m))
    msg._uid = uid
    return msg


def test_winmail_dat_wird_entpackt_und_verarbeitet(offline, cfg, plan_bytes):
    msg = _mail([("winmail.dat", _tnef([("Wirtschaftsplan_2027.xlsx", plan_bytes)]), "application/ms-tnef")])
    assert [a.filename for a in anhaenge(msg)] == ["Wirtschaftsplan_2027.xlsx"]
    assert sieht_wie_auftrag(msg)
    a = pruefe(msg, offline, cfg).antwort
    assert not a.ist_fehler and "3,37" in a.text


def test_winmail_dat_ohne_excel(offline, cfg):
    msg = _mail([("winmail.dat", _tnef([("notiz.txt", b"hallo")]), "application/octet-stream")])
    from finn.pipeline import verarbeite

    a = verarbeite(msg, offline, cfg)
    assert a.ist_fehler and "notiz.txt" in a.text


def test_kaputte_winmail_dat_wird_gemeldet(offline, cfg):
    from finn.pipeline import verarbeite

    a = verarbeite(_mail([("winmail.dat", b"kein tnef", "application/ms-tnef")]), offline, cfg)
    assert a.ist_fehler and "winmail.dat" in a.text


# --- Spam-Ordner -------------------------------------------------------------


class FakeIMAP:
    """Minimaler Ersatz für imap_tools.MailBox (nur was Postfach braucht)."""

    def __init__(self, ordner: dict[str, list]):
        self.daten = ordner
        self.aktuell = "INBOX"
        self.gelesen: list[tuple[str, str]] = []
        self.verschoben: list[tuple[str, str, str]] = []
        self.folder = NS(set=self._set)

    def _set(self, o):
        self.aktuell = o

    def fetch(self, criteria, mark_seen=False):
        return [m for m in self.daten[self.aktuell] if (self.aktuell, m.uid) not in self.gelesen]

    def flag(self, uid, flag, value):
        self.gelesen.append((self.aktuell, uid))

    def move(self, uid, ziel):
        self.verschoben.append((self.aktuell, uid, ziel))


def _postfach(tmp_path, imap, spam=True):
    p = Postfach(NS(mail_user="finn@x"), UidSpeicher(tmp_path / "u.json"),
                 spam_filter=sieht_wie_auftrag if spam else None)
    p.mb, p.spam = imap, "[Gmail]/Spam" if spam else None
    p.keys = {"INBOX": "finn@x|INBOX|1", "[Gmail]/Spam": "finn@x|[Gmail]/Spam|1"}
    return p


def test_spam_nur_auftraege_und_verschieben(tmp_path, plan_bytes):
    auftrag = _mail([("Wirtschaftsplan_2027.xlsx", plan_bytes, "application/octet-stream")], uid="5")
    werbung = _mail([], uid="6", von="werbung@spam.example")
    normal = _mail([], uid="7")
    imap = FakeIMAP({"INBOX": [normal], "[Gmail]/Spam": [auftrag, werbung]})
    p = _postfach(tmp_path, imap)
    neu = p.neue()
    assert [(m.finn_ordner, m.uid) for m in neu] == [("INBOX", "7"), ("[Gmail]/Spam", "5")]
    assert imap.aktuell == "INBOX"                       # IDLE läuft wieder auf dem Posteingang
    p.erledigt(neu[1])
    assert ("[Gmail]/Spam", "5") in imap.gelesen
    assert imap.verschoben == [("[Gmail]/Spam", "5", "INBOX")]
    assert imap.aktuell == "INBOX"
    assert [m.uid for m in p.neue()] == ["7"]            # Werbung bleibt unangetastet
    assert ("[Gmail]/Spam", "6") not in imap.gelesen


def test_spam_ohne_antwort_wird_nicht_verschoben(tmp_path, plan_bytes):
    auftrag = _mail([("x.xlsx", plan_bytes, "application/octet-stream")], uid="8", von="noreply@x.example")
    imap = FakeIMAP({"INBOX": [], "[Gmail]/Spam": [auftrag]})
    p = _postfach(tmp_path, imap)
    p.erledigt(p.neue()[0], beantwortet=False)
    assert imap.verschoben == [] and ("[Gmail]/Spam", "8") in imap.gelesen


def test_spam_lesen_abschaltbar(tmp_path, plan_bytes):
    auftrag = _mail([("x.xlsx", plan_bytes, "application/octet-stream")], uid="9")
    p = _postfach(tmp_path, FakeIMAP({"INBOX": [], "[Gmail]/Spam": [auftrag]}), spam=False)
    assert p.neue() == []


def test_config_spam_lesen(monkeypatch):
    from finn.config import lade_config

    monkeypatch.setenv("SPAM_LESEN", "0")
    assert lade_config().spam_lesen is False
    monkeypatch.setenv("SPAM_LESEN", "1")
    assert lade_config().spam_lesen is True


# --- Spielraum bis zum Grenzwert (Rechnung im Code) ---------------------------


@pytest.fixture(scope="module")
def ergebnisse():
    from finn.config import PROJEKT_ROOT

    plan = lade_plan((PROJEKT_ROOT / "data" / "Wirtschaftsplan_2027.xlsx").read_bytes())
    out = {}
    for j in sorted((REF / "extraktion").glob("*.json")):
        v = Vertrag.model_validate_json(j.read_text(encoding="utf-8"))
        z = Zuordnung.model_validate_json((REF / "zuordnung" / j.name).read_text(encoding="utf-8"))
        for e in berechne_vertrag(j.name, v, z, plan, date(2027, 12, 31)).covenants:
            out[e.kennzahl] = e
    return out


@pytest.mark.parametrize("kennzahl,treiber,aenderung", [
    ("Schuldendienstdeckungsgrad", "EBITDA", "-6216"),          # 1,30 × 23.680 − 37.000
    ("Dynamischer Verschuldungsgrad", "EBITDA", "-1457.14"),    # 135.600 / 3,5 − 40.200
    ("Eigenkapitalquote", "Eigenkapital", "-2140"),             # 30 % × 313.200 − 96.100
    ("Wirtschaftliche Eigenkapitalquote", "Eigenkapital", "-21370"),
])
def test_spielraum(ergebnisse, kennzahl, treiber, aenderung):
    sr = ergebnisse[kennzahl].spielraum
    assert sr.treiber == treiber
    assert round(sr.aenderung, 2) == D(aenderung)


def test_spielraum_trifft_grenzwert_exakt(ergebnisse):
    """Probe: mit der Änderung eingesetzt ergibt sich genau der Grenzwert."""
    e = ergebnisse["Dynamischer Verschuldungsgrad"]
    assert (e.zaehler / (e.nenner + e.spielraum.aenderung)).quantize(Decimal("0.000001")) == D("3.5")
    e = ergebnisse["Schuldendienstdeckungsgrad"]
    assert (e.zaehler + e.spielraum.aenderung) / e.nenner == D("1.3")


def test_spielraum_bei_verletzung_positiv():
    from test_calc import _einfach

    e = _einfach(12, 10, 1.30, rundung=2)          # 1,20 < 1,30 → Zähler muss steigen
    from finn.calc.covenants import berechne_spielraum

    assert berechne_spielraum(e).aenderung == D(1)
    assert "Anstieg" in fmt.spielraum_satz(berechne_spielraum(e))


def test_spielraum_in_mail_und_zusammenfassung(auftrag, offline, cfg):
    lauf = pruefe(auftrag, offline, cfg)
    assert "EBITDA −1.457 T€ (rd. 1,5 Mio. €)" in lauf.antwort.html
    assert "Spielraum bis Grenzwert" in lauf.antwort.html
    text = summary.fallback(lauf.ergebnisse, cfg.stichtag)
    assert "rd. 2,1 Mio. €" in text and "rd. 1,5 Mio. €" in text
    erlaubt = summary.erlaubte_zahlen(lauf.ergebnisse, cfg.stichtag)
    assert summary.pruefe_zahlen("Ein EBITDA-Rückgang von rd. 1,5 Mio. € (1.457 T€) reicht.", erlaubt,
                                 cfg.stichtag) == []
    assert summary.pruefe_zahlen("Ein EBITDA-Rückgang von rd. 9,9 Mio. € reicht.", erlaubt, cfg.stichtag) == ["9,9"]
    assert any("spielraum_bis_grenzwert" in f for f in summary.fakten(lauf.ergebnisse))


# --- Formel je Covenant --------------------------------------------------------


@pytest.mark.parametrize("kennzahl,formel", [
    ("Schuldendienstdeckungsgrad",
     "Schuldendienstdeckungsgrad = (EBITDA − Ertragsteuern) / (Zinsaufwand für Finanzverbindlichkeiten "
     "+ planmäßige Tilgungsleistungen auf Finanzverbindlichkeiten)"),
    ("Dynamischer Verschuldungsgrad", "Dynamischer Verschuldungsgrad = Nettofinanzverbindlichkeiten / EBITDA"),
    ("Eigenkapitalquote", "Eigenkapitalquote = Eigenkapital / Bilanzsumme (in %)"),
    ("Wirtschaftliche Eigenkapitalquote",
     "Wirtschaftliche Eigenkapitalquote = (Eigenkapital + 50 % × Sonderposten für Investitions- und "
     "Baukostenzuschüsse) / Bilanzsumme (in %)"),
])
def test_formel(ergebnisse, kennzahl, formel):
    assert fmt.formel(ergebnisse[kennzahl]) == formel


def test_formeln_zwischengroessen(ergebnisse):
    f = fmt.formeln_zwischengroessen(ergebnisse["Dynamischer Verschuldungsgrad"])
    assert f[0] == "Nettofinanzverbindlichkeiten = Finanzverbindlichkeiten − Liquide Mittel"
    assert f[1].startswith("EBITDA = Jahresüberschuss bzw. Jahresfehlbetrag + Steuern vom Einkommen")
    assert "− sonstige Zinsen und ähnliche Erträge" in f[1]


def test_formel_in_mail(auftrag, offline, cfg):
    a = pruefe(auftrag, offline, cfg).antwort
    assert "Dynamischer Verschuldungsgrad = Nettofinanzverbindlichkeiten / EBITDA" in a.html
    assert "Formel: Eigenkapitalquote = Eigenkapital / Bilanzsumme (in %)" in a.text
