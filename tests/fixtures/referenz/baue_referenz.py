"""Referenzdaten (Handanalyse Phase 1) als Extraktion/Zuordnung: python tests/fixtures/referenz/baue_referenz.py"""
from pathlib import Path

from finn.extraction.schema import (Covenant, Fundstelle as F, Grenzwert, Hinweis, Margenstufe,
                                    Quelle, Term, TermZuordnung, Vertrag, Zuordnung, Zwischengroesse,
                                    iter_terme)

root = Path(__file__).resolve().parent
(root / "extraktion").mkdir(parents=True, exist_ok=True)
(root / "zuordnung").mkdir(parents=True, exist_ok=True)

def T(b, f, v=1, art="planposition", faktor=1.0, hinweis=None):
    return Term(bezeichnung=b, art=art, vorzeichen=v, faktor=faktor, hinweis=hinweis, fundstelle=f)

GUV, BIL, FIN = "GuV", "Bilanz", "Finanzierung"
P_GUV, P_BIL = "Plan 2027", "31.12.2027 (Plan)"
def Q(blatt, zeile, spalte, ueb="wert", v=1):
    return Quelle(blatt=blatt, zeile=zeile, spalte=spalte, uebernahme=ueb, vorzeichen=v)

EBITDA_Q = {
    0: ([Q(GUV, "Jahresüberschuss", P_GUV)], "Jahresüberschuss laut Erfolgsplan"),
    1: ([Q(GUV, "Steuern vom Einkommen und vom Ertrag", P_GUV, "betrag")], "Aufwand, im Plan negativ"),
    2: ([Q(GUV, "Zinsen und ähnliche Aufwendungen", P_GUV, "betrag")], "gesamter Zinsaufwand laut GuV"),
    3: ([Q(GUV, "Sonstige Zinsen und ähnliche Erträge", P_GUV)], "Zinserträge laut GuV"),
    4: ([Q(GUV, "Abschreibungen auf immaterielle Vermögensgegenstände und Sachanlagen", P_GUV, "betrag")], "Abschreibungen laut GuV"),
    5: ([], "im Erfolgsplan keine außerordentlichen Posten ausgewiesen"),
}

def ebitda(seite, para, zitate):
    namen = ["Jahresüberschuss bzw. Jahresfehlbetrag", "Steuern vom Einkommen und vom Ertrag",
             "Zinsen und ähnliche Aufwendungen", "sonstige Zinsen und ähnliche Erträge",
             "Abschreibungen auf immaterielle Vermögensgegenstände und Sachanlagen",
             "außerordentliche Aufwendungen bzw. Erträge (§ 285 Nr. 31 HGB)"]
    vz = [1, 1, 1, -1, 1, 1]
    return Zwischengroesse(name="EBITDA", fundstelle=F(seite=seite, paragraph=para, zitat=zitate[0]),
                           terme=[T(n, F(seite=seite, paragraph=para, zitat=z), v) for n, z, v in zip(namen, zitate, vz)])

vertraege = {}
zuord = {}

# --- Vertrag 1 ---
vertraege["Vertrag_1_Sparkasse_Investitionsdarlehen"] = Vertrag(
    vertragsname="Sparkasse Musterstadt – Investitionsdarlehen Nr. 4471 203 118",
    hat_financial_covenants=False,
    begruendung="Der Vertrag enthält keine Finanzkennzahl mit Grenzwert. Die in der Präambel genannte "
                "Eigenkapitalquote und der dynamische Verschuldungsgrad zum 31.12.2019 sind nur Grundlage der "
                "Kreditentscheidung; die Kündigungsgründe in § 15 sind rein qualitativ.",
    begruendung_fundstelle=F(seite=1, paragraph="Präambel",
                             zitat="Grundlage der Kreditentscheidung der Sparkasse sind die festgestellten Jahresabschlüsse"),
)
zuord["Vertrag_1_Sparkasse_Investitionsdarlehen"] = Zuordnung(zuordnungen=[])

# --- Vertrag 2 ---
v2 = Vertrag(
    vertragsname="Förderbank Musterland – Förderdarlehen FD-2022-08817",
    hat_financial_covenants=True,
    begruendung="§ 13 verpflichtet zu einer Mindest-Wirtschaftlichen-Eigenkapitalquote.",
    covenants=[Covenant(
        kennzahl="Wirtschaftliche Eigenkapitalquote",
        definition_wortlaut="Verhältnis des Wirtschaftlichen Eigenkapitals (Eigenkapital zuzüglich 50 % der Sonderposten) zur Bilanzsumme zum Bilanzstichtag, in Prozent.",
        einheit="prozent", richtung="min", rundung_nachkommastellen=None,
        zaehler=[
            T("Eigenkapital (§ 266 Abs. 3 A HGB)", F(seite=1, paragraph="§ 1 Abs. 1", zitat="„Eigenkapital“ bezeichnet das in der Bilanz der Kreditnehmerin gemäß § 266 Absatz 3")),
            T("Sonderposten für Investitions- und Baukostenzuschüsse", F(seite=2, paragraph="§ 1 Abs. 1", zitat="„Wirtschaftliches Eigenkapital“ bezeichnet das Eigenkapital zuzüglich 50 % (fünfzig Prozent) der Sonderposten"), faktor=0.5,
              hinweis="Gesellschafterdarlehen und Rückstellungen zählen nicht zum Wirtschaftlichen Eigenkapital"),
        ],
        nenner=[T("Bilanzsumme", F(seite=1, paragraph="§ 1 Abs. 1", zitat="„Bilanzsumme“ bezeichnet die Summe der Aktiva"))],
        grenzwerte=[Grenzwert(wert=27.5, fundstelle=F(seite=6, paragraph="§ 13 Abs. 1", zitat="eine Wirtschaftliche Eigenkapitalquote von mindestens 27,5 % einzuhalten"))],
        fundstelle_definition=F(seite=2, paragraph="§ 1 Abs. 1", zitat="„Wirtschaftliche Eigenkapitalquote“ bezeichnet das Verhältnis des Wirtschaftlichen Eigenkapitals zur Bilanzsumme"),
        hinweise=[Hinweis(text="Eine Unterschreitung auf Planbasis führt zu Gesprächen über Maßnahmen, begründet aber für sich keinen Kündigungsgrund.",
                          fundstelle=F(seite=6, paragraph="§ 13 Abs. 3", zitat="Eine solche Vorschau begründet für sich genommen keinen Kündigungsgrund"))],
    )],
)
vertraege["Vertrag_2_Foerderbank_Foerderdarlehen"] = v2

# --- Vertrag 3 ---
v3 = Vertrag(
    vertragsname="Landesbank Mittelland – Investitionsdarlehen LBM-INV-2025-0412",
    hat_financial_covenants=True,
    begruendung="§ 13 i. V. m. Anlage 3 verpflichtet zu einem Mindest-Schuldendienstdeckungsgrad.",
    zwischengroessen=[ebitda(13, "Anlage 3 Abs. 2", [
        "EBITDA bezeichnet für den Berechnungszeitraum den Jahresüberschuss bzw. Jahresfehlbetrag",
        "zuzüglich der Steuern vom Einkommen und vom Ertrag",
        "zuzüglich der Zinsen und ähnlichen Aufwendungen",
        "abzüglich der sonstigen Zinsen und ähnlichen Erträge",
        "zuzüglich der Abschreibungen auf immaterielle Vermögensgegenstände des Anlagevermögens und Sachanlagen",
        "zuzüglich bzw. abzüglich außerordentlicher Aufwendungen bzw. Erträge",
    ])],
    covenants=[Covenant(
        kennzahl="Schuldendienstdeckungsgrad",
        definition_wortlaut="Quotient aus EBITDA abzüglich Ertragsteuern (Zähler) und Schuldendienst (Nenner) für denselben Berechnungszeitraum.",
        einheit="faktor", richtung="min", rundung_nachkommastellen=2,
        zaehler=[
            T("EBITDA", F(seite=13, paragraph="Anlage 3 Abs. 6", zitat="EBITDA abzüglich Ertragsteuern (Zähler)"), art="zwischengroesse"),
            T("Ertragsteuern", F(seite=13, paragraph="Anlage 3 Abs. 5", zitat="Verlustrechnung für den Berechnungszeitraum ausgewiesenen Steuern vom Einkommen und vom Ertrag"), v=-1),
        ],
        nenner=[
            T("Zinsaufwand für Finanzverbindlichkeiten", F(seite=13, paragraph="Anlage 3 Abs. 4 lit. a", zitat="dem Zinsaufwand für Finanzverbindlichkeiten; Zinsaufwendungen aus der Aufzinsung von Rückstellungen"),
              hinweis="ohne Aufzinsung von Rückstellungen; Gesellschafterdarlehen zählen unabhängig vom Rangrücktritt zu den Finanzverbindlichkeiten (Anlage 3 Abs. 3)"),
            T("planmäßige Tilgungsleistungen auf Finanzverbindlichkeiten", F(seite=13, paragraph="Anlage 3 Abs. 4 lit. b", zitat="den im Berechnungszeitraum fälligen planmäßigen Tilgungsleistungen auf Finanzverbindlichkeiten"),
              hinweis="ohne freiwillige Sondertilgungen und vorzeitige Rückzahlungen"),
        ],
        grenzwerte=[Grenzwert(wert=1.30, fundstelle=F(seite=5, paragraph="§ 13 Abs. 1", zitat="einen Schuldendienstdeckungsgrad von mindestens 1,30 einzuhalten"))],
        fundstelle_definition=F(seite=13, paragraph="Anlage 3 Abs. 6", zitat="Der Schuldendienstdeckungsgrad (Debt Service Coverage Ratio, DSCR) ist der Quotient aus"),
        hinweise=[
            Hinweis(text="Weist die Planberechnung weniger als den Mindestwert aus, muss die Kreditnehmerin binnen 30 Tagen Maßnahmen darlegen.",
                    fundstelle=F(seite=6, paragraph="§ 13 Abs. 3", zitat="innerhalb von 30 Tagen darlegen, durch welche Maßnahmen sie die Einhaltung sicherstellen")),
            Hinweis(text="Darlehen von Gesellschaftern sind Finanzverbindlichkeiten, auch bei Rangrücktritt.",
                    fundstelle=F(seite=13, paragraph="Anlage 3 Abs. 3", zitat="unabhängig davon, ob für diese Darlehen ein Rangrücktritt vereinbart ist")),
        ],
    )],
)
vertraege["Vertrag_3_Landesbank_Investitionsdarlehen"] = v3

# --- Vertrag 4 ---
v4 = Vertrag(
    vertragsname="Konsortialkredit EUR 64 Mio. (Agent Weserland Bank AG)",
    hat_financial_covenants=True,
    begruendung="§ 14 Abs. 1 enthält zwei Finanzkennzahlen.",
    zwischengroessen=[
        ebitda(2, "§ 1 Abs. 1 „EBITDA“", [
            "„EBITDA“ bezeichnet für einen Prüfungszeitraum den Jahresüberschuss bzw. Jahresfehlbetrag",
            "(a) zuzüglich der Steuern vom Einkommen und vom Ertrag",
            "(b) zuzüglich der Zinsen und ähnlichen Aufwendungen",
            "(c) abzüglich der sonstigen Zinsen und ähnlichen Erträge",
            "(d) zuzüglich der Abschreibungen auf immaterielle Vermögensgegenstände und Sachanlagen",
            "(e) zuzüglich bzw. abzüglich außerordentlicher Aufwendungen bzw. Erträge",
        ]),
        Zwischengroesse(
            name="Nettofinanzverbindlichkeiten",
            fundstelle=F(seite=3, paragraph="§ 1 Abs. 1 „Nettofinanzverbindlichkeiten“", zitat="Finanzverbindlichkeiten abzüglich der Liquiden Mittel"),
            terme=[
                T("Finanzverbindlichkeiten", F(seite=2, paragraph="§ 1 Abs. 1 „Finanzverbindlichkeiten“", zitat="jedoch jeweils mit Ausnahme von Nachrangigen Gesellschafterdarlehen"),
                  hinweis="ohne Nachrangige Gesellschafterdarlehen (qualifizierter Rangrücktritt)"),
                T("Liquide Mittel", F(seite=2, paragraph="§ 1 Abs. 1 „Liquide Mittel“", zitat="„Liquide Mittel“ bezeichnet den Kassenbestand und die Guthaben der Kreditnehmerin bei"), v=-1),
            ]),
    ],
    covenants=[
        Covenant(
            kennzahl="Eigenkapitalquote",
            definition_wortlaut="Verhältnis des bilanziellen Eigenkapitals (ohne Sonderposten, Rückstellungen und Gesellschafterdarlehen) zur Bilanzsumme zum Prüfungsstichtag, in Prozent.",
            einheit="prozent", richtung="min", rundung_nachkommastellen=1,
            zaehler=[T("Eigenkapital (bilanziell)", F(seite=2, paragraph="§ 1 Abs. 1 „Eigenkapital“", zitat="„Eigenkapital“ bezeichnet das bilanzielle Eigenkapital der Kreditnehmerin"),
                       hinweis="Sonderposten zählen ausdrücklich nicht zum Eigenkapital")],
            nenner=[T("Bilanzsumme", F(seite=1, paragraph="§ 1 Abs. 1 „Bilanzsumme“", zitat="„Bilanzsumme“ bezeichnet die Summe der Aktiva der Kreditnehmerin"))],
            grenzwerte=[Grenzwert(wert=30.0, fundstelle=F(seite=6, paragraph="§ 14 Abs. 1 lit. a", zitat="die Eigenkapitalquote zu jedem Prüfungsstichtag nicht weniger als 30,0 % beträgt"))],
            fundstelle_definition=F(seite=2, paragraph="§ 1 Abs. 1 „Eigenkapitalquote“", zitat="„Eigenkapitalquote“ bezeichnet das Verhältnis des Eigenkapitals zur Bilanzsumme"),
            hinweise=[
                Hinweis(text="Sonderposten sind nicht Teil des Eigenkapitals.", fundstelle=F(seite=2, paragraph="§ 1 Abs. 1 „Eigenkapital“", zitat="Sonderposten (insbesondere für Investitions- und Baukostenzuschüsse), Rückstellungen und Gesellschafterdarlehen sind")),
                Hinweis(text="Abweichungen auf Planbasis begründen keinen Kündigungsgrund (Frühwarnung).", fundstelle=F(seite=7, paragraph="§ 14 Abs. 3", zitat="eine Abweichung von den Grenzwerten auf Planbasis begründet keinen Kündigungsgrund")),
            ],
        ),
        Covenant(
            kennzahl="Dynamischer Verschuldungsgrad",
            definition_wortlaut="Verhältnis der Nettofinanzverbindlichkeiten zum letzten Tag des Prüfungszeitraums zum EBITDA für diesen Prüfungszeitraum.",
            einheit="faktor", richtung="max", rundung_nachkommastellen=2,
            zaehler=[T("Nettofinanzverbindlichkeiten", F(seite=2, paragraph="§ 1 Abs. 1 „Dynamischer Verschuldungsgrad“", zitat="das Verhältnis der Nettofinanzverbindlichkeiten zum letzten Tag des Prüfungszeitraums"), art="zwischengroesse")],
            nenner=[T("EBITDA", F(seite=2, paragraph="§ 1 Abs. 1 „Dynamischer Verschuldungsgrad“", zitat="zum EBITDA für diesen Prüfungszeitraum"), art="zwischengroesse")],
            grenzwerte=[Grenzwert(wert=3.50, fundstelle=F(seite=7, paragraph="§ 14 Abs. 1 lit. b", zitat="der Dynamische Verschuldungsgrad für jeden Prüfungszeitraum nicht mehr als 3,50"))],
            fundstelle_definition=F(seite=2, paragraph="§ 1 Abs. 1 „Dynamischer Verschuldungsgrad“", zitat="„Dynamischer Verschuldungsgrad“ bezeichnet für einen Prüfungszeitraum das Verhältnis"),
            hinweise=[Hinweis(text="Abweichungen auf Planbasis begründen keinen Kündigungsgrund (Frühwarnung).", fundstelle=F(seite=7, paragraph="§ 14 Abs. 3", zitat="eine Abweichung von den Grenzwerten auf Planbasis begründet keinen Kündigungsgrund"))],
        ),
    ],
    margenraster=[
        Margenstufe(kennzahl="Dynamischer Verschuldungsgrad", ueber=None, bis_einschliesslich=2.50, marge_prozent=0.95, fundstelle=F(seite=4, paragraph="§ 6 Abs. 3", zitat="kleiner oder gleich 2,50")),
        Margenstufe(kennzahl="Dynamischer Verschuldungsgrad", ueber=2.50, bis_einschliesslich=3.00, marge_prozent=1.10, fundstelle=F(seite=4, paragraph="§ 6 Abs. 3", zitat="größer als 2,50 und kleiner oder gleich 3,00")),
        Margenstufe(kennzahl="Dynamischer Verschuldungsgrad", ueber=3.00, bis_einschliesslich=None, marge_prozent=1.25, fundstelle=F(seite=4, paragraph="§ 6 Abs. 3", zitat="größer als 3,00")),
    ],
)
vertraege["Vertrag_4_Konsortialkredit"] = v4

# --- Zuordnungen ---
def mk(v, extra):
    zs = []
    for tid, t in iter_terme(v):
        if t.art != "planposition":
            continue
        name, *rest = tid.split("/")
        if name == "EBITDA":
            q, b = EBITDA_Q[int(rest[0])]
        else:
            q, b = extra[tid]
        zs.append(TermZuordnung(term_id=tid, quellen=q, nicht_im_plan=not q, begruendung=b))
    return Zuordnung(zuordnungen=zs)

zuord["Vertrag_2_Foerderbank_Foerderdarlehen"] = mk(v2, {
    "Wirtschaftliche Eigenkapitalquote/zaehler/0": ([Q(BIL, "A. Eigenkapital", P_BIL)], "Eigenkapital laut Planbilanz"),
    "Wirtschaftliche Eigenkapitalquote/zaehler/1": ([Q(BIL, "B. Sonderposten für Investitions- und Baukostenzuschüsse", P_BIL)], "Sonderposten laut Planbilanz"),
    "Wirtschaftliche Eigenkapitalquote/nenner/0": ([Q(BIL, "Summe Aktiva (Bilanzsumme)", P_BIL)], "Bilanzsumme laut Planbilanz"),
})
zuord["Vertrag_3_Landesbank_Investitionsdarlehen"] = mk(v3, {
    "Schuldendienstdeckungsgrad/zaehler/1": ([Q(GUV, "Steuern vom Einkommen und vom Ertrag", P_GUV, "betrag")], "Ertragsteuern laut Erfolgsplan"),
    "Schuldendienstdeckungsgrad/nenner/0": ([Q(FIN, "Summe Darlehen gesamt", "Zinsaufwand 2027")], "Zinsaufwand aller Darlehen inkl. Gesellschafterdarlehen, ohne Aufzinsung (Darlehensspiegel)"),
    "Schuldendienstdeckungsgrad/nenner/1": ([Q(FIN, "Summe Darlehen gesamt", "Planmäßige Tilgung 2027")], "planmäßige Tilgung aller Darlehen inkl. Gesellschafterdarlehen, ohne Sondertilgung"),
})
zuord["Vertrag_4_Konsortialkredit"] = mk(v4, {
    "Nettofinanzverbindlichkeiten/0": ([Q(BIL, "Verbindlichkeiten gegenüber Kreditinstituten", P_BIL)], "nur Bankdarlehen; nachrangiges Gesellschafterdarlehen ausgenommen, kein bilanziertes Leasing"),
    "Nettofinanzverbindlichkeiten/1": ([Q(BIL, "Kassenbestand und Guthaben bei Kreditinstituten", P_BIL)], "frei verfügbar laut Erläuterung 3"),
    "Eigenkapitalquote/zaehler/0": ([Q(BIL, "A. Eigenkapital", P_BIL)], "bilanzielles Eigenkapital ohne Sonderposten"),
    "Eigenkapitalquote/nenner/0": ([Q(BIL, "Summe Aktiva (Bilanzsumme)", P_BIL)], "Bilanzsumme laut Planbilanz"),
})

for name, v in vertraege.items():
    (root / "extraktion" / f"{name}.json").write_text(v.model_dump_json(indent=2), encoding="utf-8")
    (root / "zuordnung" / f"{name}.json").write_text(zuord[name].model_dump_json(indent=2), encoding="utf-8")
print("ok", sorted(vertraege))
