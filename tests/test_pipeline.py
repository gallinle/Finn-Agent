"""Phase 2: Durchlauf .eml-Fixture → Pipeline → fertige Antwort-Mail (offline)."""

from email import message_from_bytes
from email.message import EmailMessage

from imap_tools import MailMessage

from finn.mail.outbox import baue_email
from finn.pipeline import main, pruefe, verarbeite


def _ergebnis(lauf, kennzahl):
    return next(e for v in lauf.ergebnisse for e in v.covenants if e.kennzahl == kennzahl)


def test_durchlauf_fixture(auftrag, offline, cfg):
    lauf = pruefe(auftrag, offline, cfg)
    a = lauf.antwort
    assert not a.ist_fehler
    # Antwort an Reply-To, im selben Thread
    assert a.an == "finanzen@stadtwerke-musterstadt.example"
    assert a.betreff == "Re: Covenant-Prüfung Wirtschaftsplan 2027"
    assert a.in_reply_to == "<auftrag-2027-001@stadtwerke-musterstadt.example>"
    assert a.references == a.in_reply_to
    # Inhalt
    assert len(lauf.ergebnisse) == 4
    assert sum(len(v.covenants) for v in lauf.ergebnisse) == 4
    for s in ("34,32 %", "1,56", "30,7 %", "3,37", "keine Financial Covenants",
              "Bilanz!D22", "Finanzierung!G15", "GuV!D18", "§ 14 Abs. 1 lit. b"):
        assert s in a.html, s
        assert s in a.text, s
    assert "NEIN" not in a.html


def test_ergebnisse_entsprechen_phase1(auftrag, offline, cfg):
    lauf = pruefe(auftrag, offline, cfg)
    assert str(_ergebnis(lauf, "Schuldendienstdeckungsgrad").wert) == "1.56"
    assert str(_ergebnis(lauf, "Dynamischer Verschuldungsgrad").wert) == "3.37"
    assert str(_ergebnis(lauf, "Eigenkapitalquote").wert) == "30.7"


def test_email_header(auftrag, offline, cfg):
    a = pruefe(auftrag, offline, cfg).antwort
    m = message_from_bytes(bytes(baue_email(a, "finn@finn-agent.example")))
    assert m["To"] == "finanzen@stadtwerke-musterstadt.example"
    assert m["In-Reply-To"] == "<auftrag-2027-001@stadtwerke-musterstadt.example>"
    assert m["References"] == "<auftrag-2027-001@stadtwerke-musterstadt.example>"
    assert m.is_multipart()
    assert {p.get_content_type() for p in m.walk()} >= {"text/plain", "text/html"}


def test_antwort_an_from_ohne_reply_to(offline, cfg, plan_bytes):
    m = EmailMessage()
    m["From"] = "fremd@andere-firma.example"
    m["To"] = "finn@finn-agent.example"
    m["Subject"] = "Bitte prüfen"
    m["Message-ID"] = "<x1@andere-firma.example>"
    m["References"] = "<x0@andere-firma.example>"
    m.set_content("siehe Anhang")
    m.add_attachment(plan_bytes, maintype="application", subtype="octet-stream",
                     filename="plan.xlsx")
    a = pruefe(MailMessage.from_bytes(bytes(m)), offline, cfg).antwort
    assert a.an == "fremd@andere-firma.example"
    assert a.references == "<x0@andere-firma.example> <x1@andere-firma.example>"


def test_fehlender_anhang_gibt_fehler_antwort(offline, cfg):
    m = EmailMessage()
    m["From"] = "a@b.example"
    m["Subject"] = "ohne Anhang"
    m["Message-ID"] = "<y@b.example>"
    m.set_content("hallo")
    a = verarbeite(MailMessage.from_bytes(bytes(m)), offline, cfg)
    assert a.ist_fehler
    assert "kein Wirtschaftsplan" in a.text
    assert a.in_reply_to == "<y@b.example>"


def test_cli_schreibt_html(tmp_path, monkeypatch):
    from conftest import FIXTURES

    rc = main([str(FIXTURES / "auftrag.eml"), "--offline", "--out", str(tmp_path)])
    assert rc == 0
    html = (tmp_path / "antwort.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>") or "<html" in html
    assert (tmp_path / "antwort.eml").exists()
