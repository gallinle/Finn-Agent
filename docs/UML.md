# UML – Finn

Vier Sichten auf das System. GitHub rendert die Mermaid-Blöcke direkt; lokal z. B. mit dem
Mermaid-Plugin in PyCharm.

1. **Komponenten** – wer mit wem arbeitet (Schleife, Postfach, Pipeline, Dienste)
2. **Datenmodell** – was Claude liefert (Schema) und was der Code daraus berechnet
3. **Ablauf** – Sequenz einer Auftrags-Mail bis zur Antwort
4. **Lebenslauf einer Mail** – Zustände inkl. Wiederholungen, Aufgeben und Spam-Ordner

## 1. Komponenten (Klassendiagramm)

Module ohne eigene Klasse sind als `<<module>>` mit ihren wichtigsten Funktionen dargestellt.

```mermaid
classDiagram
    direction LR

    class main {
        <<module>>
        +main(argv) int
        +bearbeite_neue(postfach, dienste, cfg, sende, zustand) int
        +ist_automatisch(msg) str
        +mail_id(msg) str
        -_bearbeite_eine(msg, ...) int
        -_schleife(..., postfach_fabrik) int
    }
    class Zustand {
        +max_ki_versuche: int
        +max_sendeversuche: int
        +max_fehlversuche: int
        +ki_versuche: Counter
        +sendeversuche: Counter
        +fehlversuche: Counter
        +aufgegeben: set~str~
    }
    class Sperre {
        +pfad: Path
        +windows: bool
        +__enter__()
        +__exit__()
    }
    class Postfach {
        +cfg: Config
        +speicher: UidSpeicher
        +ordner: str
        +spam: str
        +spam_filter: Callable
        +ordner_liste: list~str~
        +neue() list~MailMessage~
        +erledigt(msg, beantwortet)
        +warte(timeout)
    }
    class UidSpeicher {
        +pfad: Path
        +schluessel(user, ordner, uidvalidity)$ str
        +enthaelt(schluessel, uid) bool
        +merke(schluessel, uid)
    }
    class outbox {
        <<module>>
        +baue_email(antwort, absender) EmailMessage
        +sende(cfg, antwort) EmailMessage
    }
    class Antwort {
        +an: str
        +betreff: str
        +in_reply_to: str
        +references: str
        +html: str
        +text: str
        +ist_fehler: bool
    }
    class pipeline {
        <<module>>
        +verarbeite(msg, dienste, cfg, letzter_versuch) Antwort
        +pruefe(msg, dienste, cfg) Lauf
        +anhaenge(msg) list~Anhang~
        +sieht_wie_auftrag(msg) bool
        +finde_plan_anhang(msg) Anhang
        +lade_und_pruefe_plan(anhang, planjahr) Planindex
        +antwort_huelle(msg) dict
    }
    class Anhang {
        +filename: str
        +payload: bytes
    }
    class Fehlerklassen {
        <<exceptions>>
        AuftragsFehler
        VoruebergehenderFehler
        KonfigurationsFehler
        BerechnungsFehler
        LLMFehler
        PlanFehler
    }
    class Dienste {
        <<Protocol>>
        +extrahiere(pdf, datei) Vertrag
        +ordne_zu(vertrag, plan, datei) Zuordnung
        +fasse_zusammen(ergebnisse, fakten) str
    }
    class ClaudeDienste {
        +cfg: Config
        +nur_cache: bool
        +client: Anthropic, timeout 300 s, 2 Retries
    }
    class OfflineDienste {
        +basis: Path
    }
    class llm {
        <<module>>
        +parse(client, modell, schema, system, content) T
    }
    class mapping {
        <<module>>
        +ordne_zu(client, modell, vertrag, plan, planjahr, datei) Zuordnung
        +pruefe(roh, plan, ids, planjahr) tuple
        +katalog_text(plan, planjahr) str
    }
    class verify {
        <<module>>
        +pruefe_vertrag(pdf, vertrag) list~Pruefung~
        +pruefe_grenzwerte(vertrag) list~str~
    }
    class Planindex {
        +blaetter: dict
        +notizen: dict
        +get(blatt, zeile, spalte) Zelle
        +spalten(blatt) list~str~
        +katalog() list
    }
    class covenants {
        <<module>>
        +berechne_vertrag(datei, vertrag, zuordnung, plan, stichtag) VertragsErgebnis
        +berechne_spielraum(ergebnis) Spielraum
        +runde(x, stellen) Decimal
    }
    class summary {
        <<module>>
        +fakten(ergebnisse) list~dict~
        +formuliere(client, modell, fakten, stichtag) str
        +pruefe_zahlen(text, erlaubt, stichtag) list~str~
        +fallback(ergebnisse, stichtag) str
    }
    class render {
        <<module>>
        +render(ergebnisse, zusammenfassung, ...) tuple
        +render_fehler(grund, details) tuple
    }
    class format {
        <<module>>
        +formel(ergebnis) str
        +formeln_zwischengroessen(ergebnis) list~str~
        +spielraum(sr) str
        +kennzahl / grenzwert / headroom(...) str
    }
    class Config {
        +vertraege_dir: Path
        +cache_dir: Path
        +stichtag: date
        +modell: str
        +imap_host, smtp_host, mail_user ...
        +poll_timeout: int
        +spam_lesen: bool
        +planjahr: int
    }

    main --> Postfach : liest Aufträge
    main --> outbox : sendet
    main --> pipeline : verarbeite()
    main *-- Zustand
    main ..> Sperre
    main ..> pipeline : sieht_wie_auftrag als spam_filter
    Postfach --> UidSpeicher
    outbox ..> Antwort
    pipeline --> Dienste
    pipeline ..> Anhang : entpackt winmail.dat
    pipeline --> Planindex : lade_plan()
    pipeline --> verify
    pipeline --> covenants
    pipeline --> summary
    pipeline --> render
    pipeline ..> Antwort : erzeugt
    pipeline ..> Fehlerklassen
    render --> format
    Dienste <|.. ClaudeDienste
    Dienste <|.. OfflineDienste
    ClaudeDienste --> llm : Extraktion
    ClaudeDienste --> mapping : Zuordnung
    ClaudeDienste --> summary : formuliere()
    mapping --> llm
    covenants --> Planindex
    main ..> Config
    pipeline ..> Config
```

## 2. Datenmodell (Klassendiagramm)

Links das Pydantic-Schema, das Claude befüllt (nur Struktur, Wortlaut, Fundstellen – keine
berechneten Werte). Rechts die Ergebnisse, die `calc/covenants.py` daraus berechnet.

```mermaid
classDiagram
    direction LR

    namespace Schema_Claude {
        class Vertrag {
            +vertragsname: str
            +hat_financial_covenants: bool
            +begruendung: str
        }
        class Covenant {
            +kennzahl: str
            +definition_wortlaut: str
            +einheit: prozent | faktor
            +richtung: min | max
            +rundung_nachkommastellen: int?
        }
        class Zwischengroesse {
            +name: str
        }
        class Term {
            +bezeichnung: str
            +art: planposition | zwischengroesse
            +vorzeichen: +1 | -1
            +faktor: float
            +hinweis: str?
        }
        class Grenzwert {
            +wert: float
            +gueltig_ab: str?
            +gueltig_bis: str?
        }
        class Hinweis {
            +text: str
        }
        class Margenstufe {
            +kennzahl: str
            +ueber: float?
            +bis_einschliesslich: float?
            +marge_prozent: float
        }
        class Fundstelle {
            +seite: int
            +paragraph: str
            +zitat: str
        }
        class Zuordnung
        class TermZuordnung {
            +term_id: str
            +nicht_im_plan: bool
            +begruendung: str
        }
        class Quelle {
            +blatt: str
            +zeile: str
            +spalte: str
            +vorzeichen: +1 | -1
            +uebernahme: wert | betrag
        }
    }

    namespace Wirtschaftsplan {
        class Planindex {
            +blaetter: Blatt → Zeile → Spalte → Zelle
            +notizen: Blatt → Texte
        }
        class Zelle {
            +wert: Decimal
            +ref: str
        }
    }

    namespace Berechnung {
        class VertragsErgebnis {
            +datei: str
            +warnungen: list~str~
            +fehler: str?
            +name: str
            +fehlgeschlagen(datei, vertrag, grund)$
        }
        class CovenantErgebnis {
            +kennzahl: str
            +wert_roh: Decimal
            +wert: Decimal
            +grenzwert: Decimal
            +headroom: Decimal
            +eingehalten: bool
            +zaehler: Decimal
            +nenner: Decimal
            +marge: Decimal?
        }
        class Spielraum {
            +treiber: str
            +aenderung: Decimal
        }
        class Groesse {
            +name: str
            +wert: Decimal
        }
        class Posten {
            +term_id: str
            +bezeichnung: str
            +vorzeichen: int
            +faktor: Decimal
            +basis: Decimal
            +wert: Decimal
            +nicht_im_plan: bool
        }
        class Quellwert {
            +ref: str
            +roh: Decimal
            +beitrag: Decimal
        }
    }

    Vertrag "1" *-- "*" Covenant
    Vertrag "1" *-- "*" Zwischengroesse
    Vertrag "1" *-- "*" Margenstufe
    Vertrag "1" o-- "0..1" Fundstelle : begruendung
    Covenant "1" *-- "*" Term : zaehler / nenner
    Covenant "1" *-- "1..*" Grenzwert
    Covenant "1" *-- "*" Hinweis
    Zwischengroesse "1" *-- "*" Term
    Term ..> Zwischengroesse : art=zwischengroesse (per Name)
    Term --> Fundstelle
    Grenzwert --> Fundstelle
    Hinweis --> Fundstelle
    Margenstufe --> Fundstelle

    Zuordnung "1" *-- "*" TermZuordnung
    TermZuordnung "1" *-- "*" Quelle
    TermZuordnung ..> Term : term_id
    Quelle ..> Planindex : Blatt/Zeile/Spalte
    Planindex "1" *-- "*" Zelle

    VertragsErgebnis --> Vertrag : 0..1 (fehlt, wenn Extraktion scheitert)
    VertragsErgebnis "1" *-- "*" CovenantErgebnis
    VertragsErgebnis "1" *-- "*" Groesse
    CovenantErgebnis --> Covenant
    CovenantErgebnis "1" *-- "0..1" Spielraum
    CovenantErgebnis "1" *-- "*" Posten : zaehler_posten / nenner_posten
    Groesse "1" *-- "*" Posten
    Posten "1" *-- "*" Posten : unterposten
    Posten "1" *-- "*" Quellwert
    Quellwert ..> Zelle : Blatt!Zelle
```

`Spielraum.aenderung` löst (Z + a·d) / (N + b·d) = Grenzwert nach d auf; a und b sind das Gewicht
des Treibers (EBITDA, sonst erster Zählerposten) in Zähler und Nenner.

## 3. Ablauf einer Auftrags-Mail (Sequenzdiagramm)

```mermaid
sequenceDiagram
    autonumber
    actor A as Absender
    participant IMAP as IMAP (Gmail)
    participant M as main.py
    participant P as pipeline.py
    participant D as ClaudeDienste
    participant C as Claude API
    participant V as verify.py
    participant R as calc/covenants.py
    participant S as summary.py
    participant SMTP as SMTP (Gmail)

    A->>IMAP: Auftrags-Mail mit Wirtschaftsplan_2027.xlsx
    M->>IMAP: fetch UNSEEN in INBOX und Spam-Ordner (mark_seen=False)
    IMAP-->>M: neue Mails (aus Spam nur mit Tabellen-Anhang)
    M->>M: eigene/automatische Mail? dann ohne Antwort erledigt
    M->>P: verarbeite(msg, letzter_versuch)
    P->>P: Anhänge lesen, winmail.dat entpacken, Plan indexieren (openpyxl + defusedxml)

    loop je Vertrags-PDF
        P->>D: extrahiere(pdf)
        alt Cache vorhanden (sha256 des PDF)
            D-->>P: Vertrag aus cache/extraktion
        else kein Cache
            D->>C: messages.parse(PDF-Dokument, Schema Vertrag)
            C-->>D: Vertrag (stop_reason geprüft)
            D-->>P: Vertrag (und in Cache schreiben)
        end
        P->>V: pruefe_vertrag(pdf, vertrag)
        V-->>P: nicht gefundene Zitate
        P->>D: ordne_zu(vertrag, plan)
        D->>C: messages.parse(Katalog + Terme, Enum-Schema)
        C-->>D: Zuordnung (Code validiert)
        D-->>P: Zuordnung
        P->>R: berechne_vertrag(...)
        R-->>P: VertragsErgebnis (Wert, Headroom, eingehalten, Spielraum)
        opt Fehler nur in diesem Vertrag
            P->>P: Zeile "Prüfung nicht möglich", übrige Verträge weiter
        end
    end

    P->>D: fasse_zusammen(fakten)
    D->>C: messages.parse(fertige Ergebnisse)
    C-->>D: 2–3 Sätze
    D-->>P: Text
    P->>S: pruefe_zahlen(text)
    alt unbelegte Zahl im Text oder KI-Fehler
        S-->>P: Standardtext (fallback)
    end
    P->>P: render (Jinja2: HTML + Text, Formel und Spielraum je Covenant)
    P-->>M: Antwort

    M->>SMTP: sende (In-Reply-To / References)
    SMTP-->>A: Antwort im selben Thread
    M->>M: UID merken (processed_uids.json)
    M->>IMAP: als gelesen markieren (aus Spam: in den Posteingang verschieben)
    M->>IMAP: idle.wait(60 s) auf dem Posteingang
```

## 4. Lebenslauf einer Mail (Zustandsdiagramm)

```mermaid
stateDiagram-v2
    direction TB
    [*] --> Ungelesen : Mail kommt an

    state "Ungelesen (INBOX)" as Ungelesen
    state "Ungelesen im Spam" as Spam
    state "Echter Spam (unangetastet)" as Ignoriert
    state "In Bearbeitung" as Bearbeitung
    state "Wartet auf KI-Dienst" as WartetKI
    state "Wartet auf Versand" as WartetSMTP
    state "Erledigt ohne Antwort" as OhneAntwort
    state "Beantwortet" as Beantwortet
    state "Aufgegeben bis Neustart" as Aufgegeben

    [*] --> Spam : Gmail stuft als Spam ein
    Spam --> Ignoriert : kein Tabellen-Anhang
    Spam --> Bearbeitung : Tabellen-Anhang (auch in winmail.dat)
    Ungelesen --> Bearbeitung : neue() im nächsten Durchlauf
    Ungelesen --> OhneAntwort : eigene oder automatische Mail

    Bearbeitung --> WartetKI : KI vorübergehend nicht erreichbar
    WartetKI --> Bearbeitung : nächster Durchlauf (max. 3 Versuche)
    Bearbeitung --> WartetSMTP : Versand fehlgeschlagen
    WartetSMTP --> Bearbeitung : nächster Durchlauf
    WartetSMTP --> Aufgegeben : 3 Versandversuche
    Bearbeitung --> Aufgegeben : 3 unerwartete Fehler
    Bearbeitung --> Beantwortet : Ergebnis- oder Fehler-Antwort gesendet

    Beantwortet --> [*] : UID gemerkt, gelesen, aus Spam in INBOX verschoben
    OhneAntwort --> [*] : UID gemerkt, gelesen
    Aufgegeben --> Ungelesen : Neustart von Finn
```

Nach dem dritten KI-Versuch geht eine Fehler-Antwort („KI-Dienst derzeit nicht erreichbar“)
raus – die Mail endet dann ebenfalls als *Beantwortet*. Reine Netzfehler zählen nicht als
Fehler der Mail, sondern lösen eine Neuverbindung aus.
