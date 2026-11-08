# Zeitlog (aus der Commit-Historie, 08.11.2026)

Die Dauer ist der Abstand zum vorherigen Commit. Der Beginn von Phase 1 ist aus dem Zeitpunkt geschätzt, an dem
die Vertrags-PDFs abgelegt wurden (ca. 12:20). Die Zeiten enthalten Wartezeiten auf Freigaben und Eingaben des
Auftraggebers (Dateien, API-Key, Postfach).

| Phase | Commit | Ende | Dauer | Inhalt | Umfang |
|---|---|---|---|---|---|
| 1 Analyse | `4d314ab` | 12:34 | ~14 min | Gerüst, Verträge und Excel gelesen, Handrechnung `docs/ANALYSE.md` | 32 Dateien, +956 |
| 2 .eml-Durchlauf | `c4f9a04` | 12:42 | 8 min | Pipeline, Planindex, Schema, Berechnung, Jinja2-Mail, Fixtures | 28 Dateien, +2.704 |
| 3 Extraktion | `dbd970d` | 13:00 | 18 min | Claude-Extraktion + Cache, pymupdf-Verifikation, Zuordnung, Live-Lauf | 16 Dateien, +1.982 |
| 4 Berechnung | `441d509` | 13:03 | 3 min | 32 Tests gegen die Handrechnung inkl. Fallen und Rundung | 2 Dateien, +360 |
| 5 Postfach | `b658cea` | 13:26 | 23 min | IMAP/SMTP, `python -m finn.main`, Filter für automatische Mails, Gmail-Einrichtung | 4 Dateien, +353 |
| 6 Robustheit | `76823e3` | 13:35 | 9 min | Fehlerfälle, Wiederholungen, Neuverbindung, Sperre, Logging (inkl. Live-Test 13:30) | 8 Dateien, +493 |
| 7 Doku | siehe `git log` | | | README, NOTIZ, ZEITLOG | |

**Summe Phase 1–6:** ca. 1 h 15 min (12:20–13:35).
