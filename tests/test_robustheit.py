"""Phase 6: fehlerhafte Anhänge, API-Fehler, Teilfehler, Wiederholungen, Doppelverarbeitung."""

import io
from dataclasses import replace
from email.message import EmailMessage

import anthropic
import httpx2
import openpyxl
import pytest
from imap_tools import MailMessage

from conftest import FIXTURES
from finn.dienste import OfflineDienste
from finn.extraction.llm import LLMFehler
from finn.mail.inbox import UidSpeicher
from finn.main import Sperre, Zustand, bearbeite_neue
from finn.pipeline import VoruebergehenderFehler, pruefe, verarbeite
from test_mail import FakePostfach, _Msg

_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _auftrag(anhaenge: list[tuple[str, bytes]], uid="1") -> MailMessage:
    m = EmailMessage()
    m["From"] = "k.beispiel@stadtwerke.example"
    m["Subject"] = "Covenant-Prüfung"
    m["Message-ID"] = f"<r{uid}@stadtwerke.example>"
    m.set_content("bitte prüfen")
    for name, daten in anhaenge:
        m.add_attachment(daten, maintype="application", subtype="octet-stream", filename=name)
    msg = _Msg.from_bytes(bytes(m))
    msg._uid = uid
    return msg


class KaputteDienste(OfflineDienste):
    """Offline-Dienste, die für bestimmte Verträge/Schritte Fehler werfen."""

    def __init__(self, extraktion_fehler=None, zusammenfassung_fehler=None, fuer="Vertrag_3"):
        super().__init__(FIXTURES / "referenz")
        self.ef, self.zf, self.fuer = extraktion_fehler, zusammenfassung_fehler, fuer
        self.aufrufe = 0

    def extrahiere(self, pdf, datei):
        self.aufrufe += 1
        if self.ef and datei.startswith(self.fuer):
            raise self.ef
        return super().extrahiere(pdf, datei)

    def fasse_zusammen(self, ergebnisse, fakten):
        if self.zf:
            raise self.zf
        return None


# --- Anhang ------------------------------------------------------------------


def test_kaputte_xlsx(offline, cfg):
    a = verarbeite(_auftrag([("Wirtschaftsplan.xlsx", b"kein excel")]), offline, cfg)
    assert a.ist_fehler and "konnte nicht als Wirtschaftsplan gelesen werden" in a.text
    assert "interner Fehler" not in a.text


def test_leere_xlsx(offline, cfg):
    a = verarbeite(_auftrag([("Wirtschaftsplan.xlsx", b"")]), offline, cfg)
    assert a.ist_fehler and "ist leer" in a.text


def test_altes_excel_format(offline, cfg):
    a = verarbeite(_auftrag([("Wirtschaftsplan.xls", b"\xd0\xcf\x11\xe0")]), offline, cfg)
    assert a.ist_fehler and "nicht im Format .xlsx" in a.text and "Wirtschaftsplan.xls" in a.text


def test_mehrere_xlsx(offline, cfg, plan_bytes):
    a = verarbeite(_auftrag([("a.xlsx", plan_bytes), ("b.xlsx", plan_bytes)]), offline, cfg)
    assert a.ist_fehler and "mehrere Excel-Dateien" in a.text


def test_plan_ohne_planjahr(offline, cfg):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "GuV"
    ws.append(["Position", "Ist 2024", "Plan 2025"])
    ws.append(["Jahresüberschuss", 1, 2])
    buf = io.BytesIO()
    wb.save(buf)
    a = verarbeite(_auftrag([("Plan2025.xlsx", buf.getvalue())]), offline, cfg)
    assert a.ist_fehler and "keine Werte für das Planjahr 2027" in a.text and "Plan 2025" in a.text


def test_excel_ohne_tabellen(offline, cfg):
    wb = openpyxl.Workbook()
    wb.active["A1"] = "nur Text"
    buf = io.BytesIO()
    wb.save(buf)
    a = verarbeite(_auftrag([("leer.xlsx", buf.getvalue())]), offline, cfg)
    assert a.ist_fehler and "konnte nicht als Wirtschaftsplan gelesen werden" in a.text


# --- Fehler in einzelnen Verträgen / API --------------------------------------


def test_teilfehler_ein_vertrag(auftrag, cfg):
    d = KaputteDienste(extraktion_fehler=LLMFehler("Antwort wurde bei max_tokens abgeschnitten."))
    lauf = pruefe(auftrag, d, cfg)
    a = lauf.antwort
    assert not a.ist_fehler
    assert "Prüfung nicht möglich" in a.html and "max_tokens" in a.html
    assert "PRÜFUNG NICHT MÖGLICH" in a.text
    assert "3,37" in a.html and "34,32 %" in a.html          # übrige Verträge geprüft
    assert "nicht geprüft werden konnte" in a.text            # Fallback-Zusammenfassung
    gescheitert = [v for v in lauf.ergebnisse if v.fehler]
    assert [v.datei for v in gescheitert] == ["Vertrag_3_Landesbank_Investitionsdarlehen.pdf"]


def test_ki_ablehnung_bad_request_nur_ein_vertrag(auftrag, cfg):
    e = anthropic.BadRequestError("bad", response=httpx2.Response(400, request=_REQ), body=None)
    lauf = pruefe(auftrag, KaputteDienste(extraktion_fehler=e), cfg)
    assert sum(bool(v.fehler) for v in lauf.ergebnisse) == 1


@pytest.mark.parametrize("fehler", [
    anthropic.APIConnectionError(request=_REQ),
    anthropic.APITimeoutError(request=_REQ),
    anthropic.RateLimitError("rate", response=httpx2.Response(429, request=_REQ), body=None),
    anthropic.InternalServerError("overloaded", response=httpx2.Response(529, request=_REQ), body=None),
])
def test_voruebergehende_api_fehler(auftrag, cfg, fehler):
    d = KaputteDienste(extraktion_fehler=fehler)
    with pytest.raises(VoruebergehenderFehler):
        verarbeite(auftrag, d, cfg, letzter_versuch=False)
    a = verarbeite(auftrag, d, cfg, letzter_versuch=True)
    assert a.ist_fehler and "derzeit nicht erreichbar" in a.text


def test_api_schluessel_ungueltig(auftrag, cfg):
    e = anthropic.AuthenticationError("invalid x-api-key", response=httpx2.Response(401, request=_REQ), body=None)
    a = verarbeite(auftrag, KaputteDienste(extraktion_fehler=e), cfg, letzter_versuch=False)
    assert a.ist_fehler and "Konfigurationsfehler" in a.text
    assert "x-api-key" not in a.text          # keine technischen Details an Externe


def test_zusammenfassung_fehler_nutzt_standardtext(auftrag, cfg):
    d = KaputteDienste(zusammenfassung_fehler=anthropic.APIConnectionError(request=_REQ))
    a = pruefe(auftrag, d, cfg).antwort
    assert not a.ist_fehler and "Von 4 Kreditverträgen" in a.text


def test_interner_fehler_wird_zur_fehler_antwort(auftrag, cfg):
    a = verarbeite(auftrag, KaputteDienste(extraktion_fehler=ZeroDivisionError("/geheim/pfad")), cfg)
    assert a.ist_fehler and "interner Fehler" in a.text and "Fehler-ID" in a.text
    assert "/geheim/pfad" not in a.text and "ZeroDivisionError" not in a.text


def test_fehlende_vertraege_fehler_antwort(auftrag, offline, cfg, tmp_path):
    a = verarbeite(auftrag, offline, replace(cfg, vertraege_dir=tmp_path))
    assert a.ist_fehler


# --- Polling: Wiederholungen, Sendefehler, Doppelverarbeitung ------------------


def test_ki_ausfall_wird_wiederholt_dann_fehler_antwort(tmp_path, cfg):
    cfg = replace(cfg, mail_user="finn@finn-agent.example")
    d = KaputteDienste(extraktion_fehler=anthropic.APIConnectionError(request=_REQ))
    pf = FakePostfach([_Msg.from_bytes((FIXTURES / "auftrag.eml").read_bytes())], UidSpeicher(tmp_path / "u.json"))
    pf.msgs[0]._uid = "11"
    z, gesendet = Zustand(max_ki_versuche=3), []
    for _ in range(2):
        assert bearbeite_neue(pf, d, cfg, gesendet.append, z) == 0
    assert gesendet == [] and pf.gelesen == []
    assert bearbeite_neue(pf, d, cfg, gesendet.append, z) == 1
    assert gesendet[0].ist_fehler and "nicht erreichbar" in gesendet[0].text


def test_sendefehler_nach_max_versuchen_aufgegeben(tmp_path, offline, cfg):
    cfg = replace(cfg, mail_user="finn@finn-agent.example")
    pf = FakePostfach([_auftrag([], uid="12")], UidSpeicher(tmp_path / "u.json"))
    z = Zustand(max_sendeversuche=2)
    versuche = []

    def kaputt(a):
        versuche.append(a)
        raise ConnectionError("SMTP weg")

    for _ in range(4):
        bearbeite_neue(pf, offline, cfg, kaputt, z)
    assert len(versuche) == 2 and "12" in z.aufgegeben
    assert pf.gelesen == []          # bleibt ungelesen → nach Neustart erneut


def test_sperre_verhindert_zweite_instanz(tmp_path):
    with Sperre(tmp_path / "finn.lock"):
        with pytest.raises(RuntimeError, match="läuft bereits"):
            with Sperre(tmp_path / "finn.lock"):
                pass
    with Sperre(tmp_path / "finn.lock"):   # nach Freigabe wieder möglich
        pass


def test_uid_speicher_ueberlebt_kaputte_schreibvorgaenge(tmp_path):
    p = tmp_path / "u.json"
    UidSpeicher(p).merke("k", "1")
    assert not list(tmp_path.glob(".uids-*"))   # keine Temp-Reste (atomar via os.replace)
    assert UidSpeicher(p).enthaelt("k", "1")
