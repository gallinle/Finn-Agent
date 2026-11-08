"""Erzeugt tests/fixtures/auftrag.eml (Auftrags-Mail mit Wirtschaftsplan_2027.xlsx).

    python tests/fixtures/make_auftrag.py
"""

from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

m = EmailMessage()
m["From"] = "Kerstin Beispiel <k.beispiel@stadtwerke-musterstadt.example>"
m["Reply-To"] = "finanzen@stadtwerke-musterstadt.example"
m["To"] = "finn@finn-agent.example"
m["Subject"] = "Covenant-Prüfung Wirtschaftsplan 2027"
m["Date"] = "Mon, 02 Nov 2026 09:15:00 +0100"
m["Message-ID"] = "<auftrag-2027-001@stadtwerke-musterstadt.example>"
m.set_content(
    "Hallo Finn,\n\nbitte prüfe die Financial Covenants unserer Kreditverträge auf Basis "
    "des beigefügten Wirtschaftsplans 2027 (Stichtag 31.12.2027).\n\nDanke und Gruß\nKerstin Beispiel\n"
)
m.add_attachment(
    (ROOT / "data" / "Wirtschaftsplan_2027.xlsx").read_bytes(),
    maintype="application",
    subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    filename="Wirtschaftsplan_2027.xlsx",
)
(Path(__file__).parent / "auftrag.eml").write_bytes(bytes(m))
print("geschrieben: tests/fixtures/auftrag.eml")
