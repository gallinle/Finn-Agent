# Finn – Covenant-Prüfung per E-Mail

Finn überwacht ein Postfach. Kommt eine Auftrags-Mail mit dem Wirtschaftsplan (`.xlsx`),
liest Finn die Financial Covenants der Kreditverträge in `data/vertraege/`, ordnet die
Planwerte zu, rechnet jede Kennzahl für den Stichtag 31.12.2027 und antwortet **im selben
Mail-Thread** mit Zusammenfassung, Tabelle je Vertrag/Covenant (Wert, Grenzwert, Headroom,
eingehalten) und den Fundstellen jeder Zahl – im Vertrag (Seite, §/Anlage) und im Plan
(`Blatt!Zelle`).

## Start

```bash
uv sync                        # Abhängigkeiten (Python ≥ 3.14)
cp .env.example .env           # ANTHROPIC_API_KEY + Postfach (IMAP/SMTP) in .env eintragen
uv run python -m finn.main     # Polling-Schleife starten (Strg+C beendet)
```

Gmail: `imap.gmail.com:993`, `smtp.gmail.com:465`, Passwort = App-Passwort (2FA nötig).

### Weitere Aufrufe

| Befehl | Zweck |
|---|---|
| `uv run python -m finn.main --einmal` | ungelesene Aufträge einmal abarbeiten, dann beenden |
| `uv run python -m finn.main --trocken` | nichts senden/markieren, Antworten nach `out/trocken/` |
| `uv run python -m finn.pipeline tests/fixtures/auftrag.eml` | Demo ohne Postfach → `out/antwort.html` (Verträge aus Cache) |
| `uv run python -m finn.pipeline tests/fixtures/auftrag.eml --offline` | wie oben, ganz ohne API (Referenzdaten) |
| `uv run pytest` | Tests (laufen ohne API und ohne Postfach) |

## Ablauf (`src/finn/pipeline.py`, fest – keine Agent-Schleife)

1. **Anhang prüfen**, Wirtschaftsplan mit openpyxl (`data_only=True`) indexieren:
   Blatt → Zeilenbeschriftung → Spalte → (Wert, `Blatt!Zelle`) — `plan/wirtschaftsplan.py`
2. **Verträge lesen** (Claude, `messages.parse` + Pydantic-Schema, PDF als gecachter
   `document`-Block); Ergebnis in `cache/extraktion/<sha256 des PDF>.json` — `extraction/contracts.py`
3. **Zitate verifizieren**: jedes Zitat wird mit pymupdf auf der angegebenen Seite gesucht;
   nicht gefundene werden in der Mail markiert — `extraction/verify.py`
4. **Zuordnung** Vertragsterm → Planzeile (Claude wählt nur aus vorhandenen Zeilen/Spalten,
   Code validiert) — `extraction/mapping.py`
5. **Berechnung** – ausschließlich im Code (Decimal, vertragliche Rundung) — `calc/covenants.py`
6. **Zusammenfassung**: Claude formuliert 2–3 Sätze aus den fertigen Ergebnissen; jede Zahl
   im Text wird gegen die Ergebnisse geprüft, sonst Standardtext — `report/summary.py`
7. **Antwort** deterministisch per Jinja2 (`report/templates/`), Versand per SMTP mit
   `In-Reply-To`/`References` an Reply-To bzw. From — `mail/outbox.py`

Postfach: `mail/inbox.py` (imap-tools, ungelesene Mails + IDLE, verarbeitete UIDs in
`cache/processed_uids.json`), Schleife und Fehlerbehandlung: `main.py`.

## Dateien

```
data/vertraege/*.pdf          Kreditverträge (fest hinterlegt)
data/Wirtschaftsplan_2027.xlsx Beispiel-Auftrag
docs/ANALYSE.md               Handanalyse Phase 1 (Referenz für die Tests)
cache/extraktion|zuordnung/   Claude-Ergebnisse (committet → schnelle, reproduzierbare Demo)
tests/fixtures/               auftrag.eml, Referenz-Extraktion/-Zuordnung
logs/finn.log                 Protokoll (rotierend, nicht im Repo)
NOTIZ.md                      Annahmen, Abweichungen, KI-Einsatz, nächste Schritte
ZEITLOG.md                    Zeitaufwand je Phase
```

Ändert sich ein Vertrag, ändert sich sein Hash → er wird beim nächsten Auftrag neu gelesen.
Einen Vertrag neu lesen erzwingen: die zugehörige Datei in `cache/extraktion/` löschen.
