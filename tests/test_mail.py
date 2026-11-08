"""Phase 5: Polling-Logik, UID-Speicher und Antwort-Versand (ohne echtes Postfach)."""

from dataclasses import replace
from email.message import EmailMessage

import pytest
from imap_tools import MailMessage

from conftest import FIXTURES
from finn.mail.inbox import UidSpeicher
from finn.main import bearbeite_neue, ist_automatisch, pruefe_config


class _Msg(MailMessage):
    """MailMessage mit fester UID (imap-tools liest sie sonst aus der FETCH-Antwort)."""

    _uid: str = ""

    @property
    def uid(self):
        return self._uid


def _msg(uid, **kw) -> MailMessage:
    raw = (FIXTURES / "auftrag.eml").read_bytes() if kw.pop("auftrag", False) else None
    if raw is None:
        m = EmailMessage()
        m["From"] = kw.get("von", "jemand@extern.example")
        m["Subject"] = kw.get("betreff", "Test")
        m["Message-ID"] = f"<{uid}@extern.example>"
        for k, v in kw.get("header", {}).items():
            m[k] = v
        m.set_content("ohne Anhang")
        raw = bytes(m)
    msg = _Msg.from_bytes(raw)
    msg._uid = uid
    return msg


class FakePostfach:
    def __init__(self, msgs, speicher, key="k"):
        self.msgs, self.speicher, self.key = msgs, speicher, key
        self.gelesen: list[str] = []

    def neue(self):
        return [m for m in self.msgs if m.uid not in self.gelesen
                and not self.speicher.enthaelt(self.key, m.uid)]

    def erledigt(self, m):
        self.speicher.merke(self.key, m.uid)
        self.gelesen.append(m.uid)


def test_auftrag_und_fehlerfall_werden_beantwortet(tmp_path, offline, cfg):
    cfg = replace(cfg, mail_user="finn@finn-agent.example")
    sp = UidSpeicher(tmp_path / "uids.json")
    pf = FakePostfach([_msg("1", auftrag=True), _msg("2")], sp)
    gesendet = []
    assert bearbeite_neue(pf, offline, cfg, gesendet.append) == 2
    assert [a.an for a in gesendet] == ["finanzen@stadtwerke-musterstadt.example", "jemand@extern.example"]
    assert not gesendet[0].ist_fehler and gesendet[1].ist_fehler
    assert pf.gelesen == ["1", "2"]


def test_doppelverarbeitung_ueber_neustart(tmp_path, offline, cfg):
    cfg = replace(cfg, mail_user="finn@finn-agent.example")
    msgs = [_msg("7", auftrag=True)]
    bearbeite_neue(FakePostfach(msgs, UidSpeicher(tmp_path / "u.json")), offline, cfg, lambda a: None)
    # Neustart: neuer Speicher aus Datei, Mail auf dem Server noch "ungelesen"
    gesendet = []
    pf = FakePostfach(msgs, UidSpeicher(tmp_path / "u.json"))
    assert bearbeite_neue(pf, offline, cfg, gesendet.append) == 0
    assert gesendet == []


def test_sendefehler_laesst_mail_offen(tmp_path, offline, cfg):
    cfg = replace(cfg, mail_user="finn@finn-agent.example")
    sp = UidSpeicher(tmp_path / "u.json")
    pf = FakePostfach([_msg("3", auftrag=True)], sp)

    def kaputt(a):
        raise ConnectionError("SMTP weg")

    assert bearbeite_neue(pf, offline, cfg, kaputt) == 0
    assert pf.gelesen == [] and not sp.enthaelt("k", "3")
    gesendet = []
    assert bearbeite_neue(pf, offline, cfg, gesendet.append) == 1   # nächster Durchlauf


def test_eigene_mails_werden_nicht_beantwortet(tmp_path, offline, cfg):
    cfg = replace(cfg, mail_user="finn@finn-agent.example")
    pf = FakePostfach([_msg("4", von="Finn@finn-agent.example")], UidSpeicher(tmp_path / "u.json"))
    gesendet = []
    bearbeite_neue(pf, offline, cfg, gesendet.append)
    assert gesendet == [] and pf.gelesen == ["4"]


def test_uidvalidity_trennt_speicher(tmp_path):
    sp = UidSpeicher(tmp_path / "u.json")
    sp.merke(UidSpeicher.schluessel("a@x", "INBOX", 1), "5")
    sp2 = UidSpeicher(tmp_path / "u.json")
    assert sp2.enthaelt("a@x|INBOX|1", "5")
    assert not sp2.enthaelt("a@x|INBOX|2", "5")


def test_pruefe_config_meldet_fehlende_werte(cfg):
    leer = replace(cfg, imap_host="", smtp_host="h", mail_user="", mail_password="x")
    assert pruefe_config(leer) == ["IMAP_HOST", "MAIL_USER"]


@pytest.mark.parametrize("von,header", [
    ("no-reply@accounts.google.com", {}),
    ("noreply@bank.example", {}),
    ("MAILER-DAEMON@mx.example", {}),
    ("chef@firma.example", {"Auto-Submitted": "auto-replied"}),
    ("chef@firma.example", {"Precedence": "bulk"}),
    ("liste@firma.example", {"List-Id": "<finanzen.firma.example>"}),
])
def test_automatische_mails_werden_nicht_beantwortet(tmp_path, offline, cfg, von, header):
    cfg = replace(cfg, mail_user="finn@finn-agent.example")
    m = _msg("9", von=von, header=header)
    assert ist_automatisch(m)
    pf = FakePostfach([m], UidSpeicher(tmp_path / "u.json"))
    gesendet = []
    bearbeite_neue(pf, offline, cfg, gesendet.append)
    assert gesendet == [] and pf.gelesen == ["9"]


def test_normale_mail_ist_nicht_automatisch():
    assert ist_automatisch(_msg("1", auftrag=True)) is None
    assert ist_automatisch(_msg("2", von="k.beispiel@firma.example", header={"Auto-Submitted": "no"})) is None
