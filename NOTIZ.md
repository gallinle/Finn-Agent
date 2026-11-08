# Notiz

## Annahmen (mit dem Auftraggeber in Phase 1 abgestimmt)
- Stichtag 31.12.2027; Planwerte aus „Plan 2027“, „31.12.2027 (Plan)“ und Darlehensspiegel 2027; Beträge in T€.
- Vertrag 2 schreibt keine Rundung vor → Vergleich ungerundet, Anzeige mit 2 Nachkommastellen.
- Außerordentliche Posten (§ 285 Nr. 31 HGB) weist der Plan nicht aus → mit 0 angesetzt, in der Mail vermerkt.
- Das Gesellschafterdarlehen hat laut Plan-Erläuterung einen qualifizierten Rangrücktritt → in Vertrag 4 aus den
  Finanzverbindlichkeiten ausgenommen, in Vertrag 3 (Anlage 3 Abs. 3: „unabhängig vom Rangrücktritt“) einbezogen.
- Planbasierte Werte sind laut allen Verträgen nur Frühwarnung → Hinweis in der Mail. Das Margenraster
  (Vertrag 4) steht als Info-Zeile darin, ist aber kein Covenant.
- Die Vertrags-PDFs liegen fest in `data/vertraege/`; per Mail kommt nur der Wirtschaftsplan.

## Abweichungen von der Vorgabe
- **Excel-Index nach Spaltenkopf statt nach Jahr:** Der Darlehensspiegel hat nur 2027, seine Spalten sind
  Messgrößen (Tilgung, Zinsaufwand …). In GuV und Bilanz entsprechen die Spaltenköpfe weiter den Jahren.
- **Zwischengrößen** (EBITDA, Nettofinanzverbindlichkeiten …) als eigene Ebene im Schema, damit Zwischenwerte
  belegbar sind und Begriffe je Vertrag unterschiedlich definiert werden können.
- **Auch die Zuordnung wird gecacht** (Schlüssel: Hash aus Vertrag und Plan-Katalog), nicht nur die Extraktion.
- **Kein Modellwechsel bei Ablehnung (`fallbacks`):** Er bräuchte den Beta-Endpunkt statt `client.messages.parse()`.
  Eine Ablehnung führt zu einer Fehlerzeile für diesen Vertrag. `max_tokens` für die Extraktion liegt bei 21.000,
  der SDK-Obergrenze ohne Streaming.
- **Gmail statt Outlook:** Microsoft 365 lässt meist keine Anmeldung mit Benutzername und Passwort mehr zu
  (OAuth2 nötig). Gmail funktioniert mit App-Passwort.
- **Keine Antwort auf automatische Mails** (no-reply, Auto-Submitted, Precedence, Mailinglisten) und eigene Mails,
  obwohl laut Vorgabe auch fremde Absender eine Antwort bekommen. Sonst drohen Mail-Schleifen, im Test-Postfach
  lag z. B. schon eine Google-Sicherheitswarnung.
- **Als gelesen markiert wird erst nach erfolgreichem Versand** (`mark_seen=False`). Maßgeblich ist der lokale
  UID-Speicher.
- **Zuordnung mit einem festen zweiten Versuch,** falls die Code-Prüfung scheitert. Das ist keine Agent-Schleife.

## KI-Einsatz
- **Im Produkt:** Claude Opus 5.5 liest die Verträge, ordnet Terme Planzeilen zu und formuliert die
  Zusammenfassung. Gerechnet wird nie per KI. Absicherung:
  - Pydantic-Schemas, `stop_reason`-Prüfung
  - Zitatprüfung im PDF, Grenzwert muss im Zitat stehen
  - Auswahl der Zeilen nur aus Enum-Listen
  - Zahlenprüfung der Zusammenfassung
  - Abgleich gegen die Handrechnung in Tests
- **In der Entwicklung:** Claude Code hat Analyse, Code, Tests und Doku Phase für Phase erstellt. Der Auftraggeber
  hat nach jeder Phase geprüft und freigegeben. Die Handanalyse (Phase 1) wurde mit Decimal nachgerechnet und vom
  Auftraggeber bestätigt.

## Nächste Schritte
- OAuth2 (Microsoft 365 / Google Workspace) statt App-Passwort; Betrieb als systemd-Dienst mit Alarm bei CRITICAL.
- Prompt- und Schema-Version in den Cache-Schlüssel aufnehmen; kurzer Anzeigename je Vertrag.
- Evaluationsset mit weiteren Verträgen (Staffeln, Tranchen, Equity Cure), um die Extraktion zu messen.
- Mehrere Planjahre oder Ist-Werte prüfen; Vertrags-PDFs optional per Mail entgegennehmen.
- Streaming für sehr lange Verträge (über dem `max_tokens`-Limit ohne Streaming).
