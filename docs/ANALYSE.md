# Phase 1 – Analyse (Referenz für Tests)

Stichtag: Plan 2027 = 31.12.2027 · Quelle: `data/Wirtschaftsplan_2027.xlsx`, Spalte **D** (Plan 2027), alle Werte in T€.
Hinweis: Aufwendungen stehen im Excel **negativ** (z. B. `GuV!D13 = -5100`) → die Zuordnung muss das Vorzeichen kennen.

## Vertrag 1 – Sparkasse, Investitionsdarlehen Nr. 4471 203 118 (EUR 25 Mio.)
**Keine Financial Covenants.**
- Falle: Die Präambel (S. 1) nennt eine EK-Quote von 28,4 % und einen dynamischen Verschuldungsgrad von 2,9 zum 31.12.2019. Das ist nur die *Grundlage der Kreditentscheidung*, kein Grenzwert.
- Die Kündigungsgründe in § 15 (S. 7) sind nur qualitativ (wesentliche Verschlechterung, Drittverzug > EUR 2,5 Mio.). § 12 (S. 6) regelt nur Informationspflichten.

## Vertrag 2 – Förderbank, Förderdarlehen FD-2022-08817 (EUR 30 Mio.)
**Wirtschaftliche Eigenkapitalquote ≥ 27,5 %** – § 13 Abs. 1, S. 6
- Definitionen in § 1 Abs. 1, S. 1–2:
  - „Eigenkapital“: § 266 Abs. 3 A HGB
  - „Sonderposten“: Investitions- und Baukostenzuschüsse
  - „Wirtschaftliches Eigenkapital“ = EK + **50 %** Sonderposten; Gesellschafterdarlehen zählen *nicht* dazu, auch nicht mit Rangrücktritt
  - Quote = Wirtschaftliches EK / Bilanzsumme
- Muster der Kennzahlenbescheinigung: Anlage 2, S. 13.
- Rundungsregel: keine. Annahme: Vergleich ungerundet, Anzeige mit 2 Nachkommastellen.
- § 13 Abs. 3: Eine Planvorschau unter dem Grenzwert führt nur zu Gesprächen, nicht zur Kündigung.

| Term | Zelle | Wert |
|---|---|---|
| Eigenkapital | Bilanz!D22 | 96.100 |
| Sonderposten | Bilanz!D23 | 22.800 → 50 % = 11.400 |
| Bilanzsumme | Bilanz!D15 | 313.200 |

**Ergebnis: 107.500 / 313.200 = 34,32 % · Headroom +6,82 Prozentpunkte · eingehalten**

## Vertrag 3 – Landesbank, LBM-INV-2025-0412 (EUR 40 Mio., Tranche A 25 Mio. + Tranche B 15 Mio.)
**Schuldendienstdeckungsgrad (DSCR) ≥ 1,30** – § 13 Abs. 1, S. 5
- Definitionen: Anlage 3, S. 13. Berechnung auf Planbasis nach Anlage 3 Abs. 7, Rundung kaufmännisch auf 2 Nachkommastellen (Abs. 6). Heilung nach § 13 Abs. 4, S. 6.
- DSCR = (EBITDA − Ertragsteuern) / Schuldendienst
- EBITDA (Abs. 2) = JÜ + Steuern + Zinsaufwand − Zinserträge + Abschreibungen ± ao. Posten (§ 285 Nr. 31 HGB; im Plan keine)
  - 10.700 (GuV!D18) + 3.200 (GuV!D17) + 5.100 (GuV!D13) − 300 (GuV!D12) + 21.500 (GuV!D9) = **40.200**
  - Gegenprobe: Betriebsergebnis 18.700 (GuV!D11) + Abschreibungen 21.500 = 40.200
- Zähler: 40.200 − 3.200 = **37.000**
- Schuldendienst (Abs. 4) = Zinsen auf Finanzverbindlichkeiten + planmäßige Tilgung
  - Zinsen: 4.930 (Finanzierung!G15). Das ist 5.100 abzüglich 170 Aufzinsung Pensionen (GuV!D14), die ausdrücklich ausgeschlossen ist.
  - Tilgung: 18.750 (Finanzierung!D15)
  - Summe: **23.680**
- **Fallen:**
  - Die Sondertilgung von 3.000 (Finanzierung!E8) ist ausgeschlossen.
  - Das **Gesellschafterdarlehen zählt hier mit**: Anlage 3 Abs. 3 lit. d „unabhängig davon, ob … Rangrücktritt“. Zins 220 (G13), Tilgung 1.000 (D13).
  - Die Altdarlehen zählen mit (rein planmäßige Annuitätentilgung, Finanzierung!A24).
- Tranche B (15.000, Auszahlung Q2/2027) wird erst ab 31.03.2028 getilgt. Die Tilgung der Landesbank 2027 sind 3.000 = 4 × 750 (Tranche A).

**Ergebnis: 37.000 / 23.680 = 1,5625 → 1,56 · Headroom +0,26 · eingehalten**
(Gegenproben: ohne Gesellschafterdarlehen 1,65; mit Sondertilgung 1,39)

## Vertrag 4 – Konsortialkredit, 30.11.2023 (EUR 64 Mio., Agent Weserland Bank)
Definitionen in § 1 Abs. 1, S. 2–3. Covenants in § 14 Abs. 1, S. 6–7. Rundung nach § 14 Abs. 2, S. 7: EK-Quote auf 1 Nachkommastelle, DVG auf 2 Nachkommastellen. Planbasis nach § 14 Abs. 3: nur Frühwarnung, kein Kündigungsgrund.

**a) Eigenkapitalquote ≥ 30,0 %** – § 14 Abs. 1 lit. a, S. 6
- Eigenkapital = rein bilanziell. **Sonderposten zählen ausdrücklich nicht**, anders als in Vertrag 2.
- 96.100 (Bilanz!D22) / 313.200 (Bilanz!D15) = 30,68 % → **30,7 % · Headroom +0,7 Prozentpunkte · eingehalten (knapp)**
- Falle: Mit Sonderposten ergäbe sich fälschlich 38,0 %.

**b) Dynamischer Verschuldungsgrad ≤ 3,50** – § 14 Abs. 1 lit. b, S. 7
- Nettofinanzverbindlichkeiten = Finanzverbindlichkeiten **ohne nachrangige Gesellschafterdarlehen** − Liquide Mittel
  - Das Gesellschafterdarlehen hat einen qualifizierten Rangrücktritt nach § 39 Abs. 2 InsO (Bilanz!A39). Es fällt damit unter die Ausnahme.
  - Operating Leasing ist nicht bilanziert (Bilanz!A41). Die sonstigen Verbindlichkeiten sind unverzinslich und keine Finanzverbindlichkeiten.
  - 148.200 (Bilanz!D28) − 12.600 (Bilanz!D12) = **135.600**
- EBITDA: dieselbe Definition wie in Vertrag 3 (Auflösung der Sonderposten wird nicht bereinigt) = **40.200**
- 135.600 / 40.200 = 3,3731 → **3,37 · Headroom +0,13 · eingehalten (knapp)**
- **Falle:** Mit Gesellschafterdarlehen (8.000, Bilanz!D29) ergäbe sich 3,57, also ein Bruch.
- Nur informativ, kein Covenant: Margenraster § 6 Abs. 3, S. 4. Bei 3,37 > 3,00 gilt eine Marge von 1,25 % p. a.

## Zusammenfassung
| Vertrag | Covenant | Wert | Grenze | Headroom | OK |
|---|---|---|---|---|---|
| 1 Sparkasse | – keine – | | | | |
| 2 Förderbank | Wirtsch. EK-Quote | 34,32 % | ≥ 27,5 % | +6,82 Pp | ja |
| 3 Landesbank | DSCR | 1,56 | ≥ 1,30 | +0,26 | ja |
| 4 Konsortial | EK-Quote | 30,7 % | ≥ 30,0 % | +0,7 Pp | ja |
| 4 Konsortial | Dyn. Verschuldungsgrad | 3,37 | ≤ 3,50 | +0,13 | ja |
