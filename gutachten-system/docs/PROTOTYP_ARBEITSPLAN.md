# Prototyp-Arbeitsplan Gutachten-Aufbereitung

Stand: 2026-06-09

## 1. Ziel der aktuellen Version

Diese Version ist ein lokaler Web-Prototyp fuer die teilautomatisierte
Aufbereitung technischer Gutachten im Bereich Tiefgarage, Beton, Chlorid und
Karbonatisierung.

Der Prototyp soll noch kein vollstaendig fertiges Word-Gutachten erzwingen.
Wichtiger ist aktuell, dass jeder Arbeitsschritt sauber sichtbar, pruefbar und
manuell korrigierbar ist.

Primaere Ausgabe fuer diese Version:

- saubere Mastertabelle
- bereinigte Laborwerte
- erfasste Vor-Ort-Werte
- manuell bestaetigte Bildzuordnung
- Status- und Pruefliste je Schritt

Spaetere Ausgabe:

- Word-Dokument
- LaTeX-PDF
- Exportpaket mit Tabellen, Bildzuordnung und Pruefbericht

## 2. Grundsaetze

- Originaldateien werden nie ueberschrieben.
- Alle Werte bleiben nachvollziehbar bis zur Quelle.
- Zahlen werden exakt uebernommen.
- Unklare Angaben werden nicht erfunden.
- Automatische Erkennung ist nur ein Vorschlag.
- Jeder fachlich relevante Vorschlag muss bestaetigt oder korrigiert werden.
- Karbonatisierung und Schlussfolgerungen bleiben SV-Freigabe.
- Der Prototyp soll Arbeit abnehmen, aber keine fachliche Verantwortung ersetzen.

## 3. Referenzmaterial im Workspace

Reales Beispielprojekt:

`0911_GA_EDER_GARAGE_ExampleStreet_34_ExampleTown_WE`

Wichtige Referenzdateien:

- `ExampleStreet Chloride_17-03-2025.xlsx`
  - schlecht formatierte Labor-Excel
  - relevante Werte liegen quer ueber Spalten
  - Beispielstruktur: Probenbezeichnungen in einer Zeile, Chloridwerte in einer
    spaeteren Zeile
- `Chloride_17-03-2025/CHLORID ExampleStreet.xlsx`
  - sehr aehnliche Laborwert-Datei
- `NHT_NOTIZEN erfasst.xlsx`
  - gut formatierte, bereits erfasste Referenz
  - enthaelt mehrere Tabellenblaetter mit typischer Struktur fuer Position,
    Bohrtiefe, Hoehe, Chlorid und Karbonatisierung
- `GUTACHTEN.docx`
  - bestehende Gutachtenvorlage bzw. Referenz fuer Aufbau und Textlogik
- `BA_22_01_2025/*.JPG`
  - chronologische Fotoquelle fuer Beprobungsstellen und Karbonatisierung

## 4. Aktueller Prototyp-Scope

In dieser Version enthalten:

1. Projekt lokal anlegen.
2. Dateien importieren und sichern.
3. Dateien klassifizieren.
4. Labor-Excel erkennen und in einfache Chloridwert-Tabelle ueberfuehren.
5. Vor-Ort-Werte manuell oder halbautomatisch erfassen.
6. Probennummern normalisieren.
7. Proben zu Beprobungsstellen gruppieren.
8. Mastertabelle erzeugen.
9. Fotos chronologisch anzeigen.
10. User waehlt und bestaetigt Positionsbilder pro Beprobungsstelle.
11. Karbonatisierungswert als freie Eingabe erfassen, aber ohne KI-Bildanalyse
    als Pflichtbestandteil.
12. Pruefstatus je Schritt anzeigen.
13. Mastertabelle und Bildzuordnung exportierbar machen.

In dieser Version bewusst verschoben:

- vollautomatische OCR handschriftlicher Tabellen
- KI-Messlinien fuer Karbonatisierungsbilder
- automatische finale Karbonatisierungsbewertung
- fertiger Word-Export als Muss
- LaTeX-PDF als Muss
- Cloudbetrieb
- Rollen, Login und Rechteverwaltung
- verbindliche Anonymisierung
- Sanierungsempfehlungen

## 5. Ziel-Datenmodell

### 5.1 Projekt

Pflichtfelder:

- Projektname
- Objekt / Adresse
- Auftraggeber
- Besichtigungsdatum
- Sachverstaendiger
- Bearbeiter
- Projektstatus

Dateibereiche:

- `00_original` fuer unveraenderte Originale
- `01_working` fuer Arbeitskopien
- `02_processed` fuer bereinigte Zwischendaten
- `03_images` fuer importierte oder referenzierte Bilder
- `04_tables` fuer Mastertabellen
- `05_exports` fuer spaetere Ausgaben
- `06_review` fuer Pruefberichte

### 5.2 Probe

Felder:

- `probe_id`, z. B. `P01`
- urspruengliche Probenschreibweise
- Position
- Bohrtiefe in mm
- Hoehe in cm oder `-`
- Beprobungsstelle / Gruppen-ID
- Chloridwert als Anzeige, z. B. `> 6,00`
- Chloridwert numerisch, falls ableitbar
- Einheit
- Karbonatisierung als freie Eingabe
- Bemerkung
- Status
- Quellenverweise

### 5.3 Beprobungsstelle

Felder:

- Stellen-ID
- zugehoerige Proben, z. B. `P01`, `P02`
- Position
- Hoehe
- Tiefenstufen
- ausgewaehltes Positionsbild
- optional zweites Positionsbild
- Karbonatisierungswert
- Karbonatisierungsbild(er)
- User-Bestaetigung
- offene Pruefpunkte

### 5.4 Bildzuordnung

Felder:

- Dateiname
- relativer Pfad
- Aufnahmedatum aus EXIF, falls vorhanden
- Sortiernummer
- Bildtyp: Positionsbild, Karbonatisierung, Anlage, unklar
- zugeordnete Probe oder Beprobungsstelle
- User-Bestaetigung
- Bildunterschrift / Notiz

## 6. Vollstaendiger Arbeitsablauf fuer den Prototyp

### Schritt 1: Projekt anlegen

Aufgabe:

Ein neues lokales Projekt wird mit Basisdaten angelegt.

Eingabe:

- Projektname
- Objekt
- Auftraggeber
- Datum
- Sachverstaendiger
- Bearbeiter

Ergebnis:

- Projektordner
- initiale Projektstatusdatei
- leerer Workflow mit allen Schritten

Pruefung:

- Projekt laesst sich wieder oeffnen.
- Es gibt noch keine veraenderten Originaldateien.

### Schritt 2: Dateien importieren

Aufgabe:

Alle relevanten Dateien werden in das Projekt uebernommen oder referenziert.

Erwartete Dateien:

- Labor-Excel
- gut formatierte Referenz- oder Notiztabelle
- Gutachtenvorlage oder Referenzgutachten
- Bildordner
- PDF-Anlagen
- weitere Projektdateien

Regeln:

- Originale kommen nach `00_original`.
- Originale werden nicht veraendert.
- Bei Namenskonflikten wird eine Kopie mit eindeutiger Kennung erstellt.

Ergebnis:

- Datei-Inventar mit Kategorie, Pfad, Groesse und Datum

### Schritt 3: Dateien klassifizieren

Aufgabe:

Das System schlaegt fuer jede Datei eine Kategorie vor.

Kategorien:

- Laborwerte
- Vor-Ort-Tabelle / Notizen
- Gutachtenvorlage
- Bildordner
- Anlage
- unklar

Regeln:

- User kann jede Kategorie manuell korrigieren.
- Unklare Dateien bleiben sichtbar.

Ergebnis:

- bestaetigtes Datei-Inventar

### Schritt 4: Labor-Excel analysieren

Aufgabe:

Die schlecht formatierte Labor-Excel wird in eine saubere Tabelle ueberfuehrt.

Beobachtung aus Referenz:

- Werte liegen nicht in einer klassischen Zeilentabelle.
- Proben stehen quer in Spalten.
- Chloridwerte stehen in einer gemeinsamen Messwertzeile.
- Beispielwerte wie `> 6,00` muessen exakt erhalten bleiben.

Extrahierte Felder:

- Probennummer
- Originalbezeichnung
- Chloridwert als Text
- Chloridwert numerisch, falls moeglich
- Einheit
- Zellquelle
- Vertrauensstatus

Regeln:

- Keine Rundung.
- `> 6,00` bleibt exakt als Anzeige erhalten.
- Numerischer Hilfswert darf nur fuer Sortierung und Markierung verwendet werden.
- Bei unklarem Layout wird eine Vorschautabelle gezeigt.

Ergebnis:

- `clean_lab_values.xlsx`
- strukturierte Laborwerte im Projektstatus

### Schritt 5: Vor-Ort-Werte erfassen

Aufgabe:

Die Werte aus handschriftlichen oder bereits erfassten Notizen werden in eine
saubere digitale Tabelle gebracht.

Felder:

- Proben-Nr.
- Position
- Bohrtiefe `[mm]`
- Hoehe `[cm]`
- optional Karbonatisierung
- Bemerkung

Regeln:

- Zahlen haben Vorrang.
- Unlesbare Positionen nicht erfinden.
- Fehlende Hoehe als `-` ausgeben.
- Position darf leer bleiben, wenn sie unsicher ist.
- Freie manuelle Eingabe muss immer moeglich sein.

Version-1-Entscheidung:

- OCR ist nicht Pflicht.
- Eine manuelle Eingabemaske mit Tabelle ist ausreichend.
- Eine Bildansicht neben der Eingabe kann spaeter ergaenzt werden.

Ergebnis:

- `field_measurements.xlsx`
- Vor-Ort-Werte im Projektstatus

### Schritt 6: Probennummern normalisieren

Aufgabe:

Alle Probennummern werden in ein einheitliches Format gebracht.

Ziel:

```text
P01
P02
P03
...
P10
P11
```

Regeln:

- `1`, `01`, `P1`, `Probe 1` werden zu `P01`.
- Originalschreibweise wird zusaetzlich gespeichert.
- Doppelte Zielnummern werden als Konflikt markiert.

Ergebnis:

- eindeutige Probenliste im PXX-Format

### Schritt 7: Bohrtiefe und Hoehe pruefen

Aufgabe:

Bohrtiefen und Hoehen werden formal geprueft.

Regeln:

- Bohrtiefe bleibt als einzelner Wert in der Mastertabelle.
- Tiefenbereiche fuer Bildtexte werden spaeter aus gruppierten Proben berechnet.
- Fehlende Hoehe wird als `-` gesetzt.

Beispiel:

```text
P01: Bohrtiefe 18 mm
P02: Bohrtiefe 42 mm
Bildtext spaeter: P01 0-18 mm, P02 18-42 mm
```

Ergebnis:

- validierte Feldwerte
- Warnungen bei fehlenden oder ungewoehnlichen Angaben

### Schritt 8: Proben gruppieren

Aufgabe:

Proben werden zu Beprobungsstellen zusammengefasst.

Primaere Regel:

- gleiche Position = gleiche Beprobungsstelle

Sekundaere Regel:

- paarweise gruppieren: `P01/P02`, `P03/P04`, `P05/P06`

Wichtig:

- Diese Regel ist fuer den Prototyp ein Vorschlag.
- User muss Gruppen bestaetigen oder korrigieren koennen.
- Einzelproben und Sonderfaelle muessen erlaubt sein.

Ergebnis:

- Liste der Beprobungsstellen
- Probenzuordnung je Stelle

### Schritt 9: Laborwerte mit Vor-Ort-Werten verbinden

Aufgabe:

Laborwerte werden ueber die normalisierte Probennummer mit den Vor-Ort-Werten
verbunden.

Regeln:

- Match ueber `PXX`.
- Kein Laborwert: `kein Wert vorhanden`.
- Hinweis wie `Eisen getroffen` oder `Bewehrung getroffen` wird uebernommen,
  falls vorhanden.
- Fehlende Werte bleiben in der Pruefliste sichtbar.

Ergebnis:

- vorlaeufige Mastertabelle

### Schritt 10: Mastertabelle erzeugen

Aufgabe:

Eine zentrale Tabelle wird erzeugt, die alle relevanten Probeninformationen
buendelt.

Spalten:

```text
Proben-Nr.
Position
Bohrtiefe [mm]
Hoehe [cm]
%Cl(Zement) Masse-%
Karbonatisierung [Tiefe in mm]
Beprobungsstelle
Positionsbild
Karbonatisierungsbild
Status
```

Regeln:

- Chlorid-Anzeige bleibt originalnah.
- Karbonatisierung ist vorerst freie Eingabe.
- Bildfelder duerfen leer sein, bis User bestaetigt.

Ergebnis:

- `Master_Probenliste.xlsx`
- Mastertabelle im Web sichtbar

### Schritt 11: Chlorid-Markierung anwenden

Aufgabe:

Markierungen werden fuer die Tabelle vorbereitet.

Aktuelle sichere Regel:

```text
Chlorid > 1,0 % = rot
```

Prototyp-Regel:

- Rot darf als Vorschlag angezeigt werden, wenn `> 1,0 %` sicher zutrifft.
- Orange wird nicht automatisch verwendet.
- Werte zwischen `0,2 %` und `1,0 %` werden hoechstens als fachlich zu pruefen
  markiert, nicht orange.
- Unsichere fachliche Logik bleibt im Fragenordner.

Ergebnis:

- Markierungsvorschlag in Mastertabelle
- keine ungepruefte Orange-Logik

### Schritt 12: Bilder importieren und sortieren

Aufgabe:

Der Bildordner wird eingelesen und chronologisch sortiert.

Sortierquellen:

- EXIF-Aufnahmedatum, falls vorhanden
- Dateiname
- Dateisystemdatum
- manuelle Reihenfolge

Regeln:

- Chronologie ist nur ein Vorschlag.
- User kann jedes Bild manuell verschieben oder anders zuordnen.
- Bilder werden nicht automatisch geloescht.

Ergebnis:

- Bildliste mit Vorschau und Sortierung

### Schritt 13: Positionsbilder zuordnen

Aufgabe:

Pro Beprobungsstelle wird mindestens ein Positionsbild ausgewaehlt.

Regeln:

- User bestaetigt jedes Positionsbild selbst.
- Normalerweise reicht ein Bild pro Beprobungsstelle.
- Bei schlechter Erkennbarkeit kann ein zweites Bild zugeordnet werden.
- Das Bild soll Orientierung geben: Parkplatznummer, Saeule, Wandscheibe,
  Umgebung oder andere erkennbare Merkmale.

UI-Idee:

- links Bildstreifen in chronologischer Reihenfolge
- rechts aktuelle Beprobungsstelle mit Proben, Position und Tiefen
- Buttons: `zuordnen`, `zweites Bild`, `skip`, `unklar`

Ergebnis:

- bestaetigte Bildzuordnung je Beprobungsstelle

### Schritt 14: Bildtexte vorbereiten

Aufgabe:

Aus Probenwerten und Gruppierung werden Vorschlaege fuer Bildtexte erzeugt.

Inhalt:

- Probennummern
- Position
- Bohrtiefe oder Tiefenbereiche
- Hoehe

Beispiel:

```text
P01: 0-18 mm, Hoehe 15 cm
P02: 18-42 mm, Hoehe 15 cm
Position: WS Einfahrt
```

Regeln:

- Texte sind editierbar.
- Leere Positionen bleiben leer oder werden als `Position offen` markiert.

Ergebnis:

- Bildtextvorschlaege fuer spaeteren Bericht oder LaTeX/PDF

### Schritt 15: Karbonatisierung erfassen

Aufgabe:

Karbonatisierungswerte werden pro Beprobungsstelle erfasst.

Version-1-Entscheidung:

- Keine verpflichtende KI-Bildmessung.
- Keine automatische finale Bewertung.
- Freie Eingabe ist erlaubt.
- Auswahlhilfen koennen angeboten werden, aber duerfen freie Eingabe nicht
  ersetzen.

Moegliche Werte:

```text
25 mm
35 mm
45 mm
an Bewehrung
-
nicht bestimmbar
```

Regeln:

- Karbonatisierung gilt pro Beprobungsstelle.
- Wert wird auf alle zugehoerigen Proben uebertragen.
- `an Bewehrung` wird nur nach User/SV-Bestaetigung eingetragen.

Ergebnis:

- Karbonatisierungswert je Beprobungsstelle
- uebertragener Wert je Probe in der Mastertabelle

### Schritt 16: Tabellenansichten erzeugen

Aufgabe:

Aus der Mastertabelle werden separate Ansichten erzeugt.

Ansicht 1: einfache Beprobungsstellen-Tabelle

```text
Proben-Nr.
Position
Bohrtiefe [mm]
Hoehe [cm]
```

Ansicht 2: End-/Mastertabelle

```text
Proben-Nr.
Position
Bohrtiefe [mm]
Hoehe [cm]
%Cl(Zement) Masse-%
Karbonatisierung [Tiefe in mm]
```

Regeln:

- einfache Tabelle enthaelt keine Chloridwerte
- einfache Tabelle enthaelt keine Karbonatisierung
- Farben nur in der End-/Mastertabelle

Ergebnis:

- klare Exporttabellen fuer spaetere Gutachtenausgabe

### Schritt 17: Pruefliste anzeigen

Aufgabe:

Das System zeigt pro Projekt alle offenen Punkte.

Pruefbereiche:

- fehlende Position
- fehlende Bohrtiefe
- fehlende Hoehe
- fehlender Laborwert
- unbestaetigte Gruppierung
- fehlendes Positionsbild
- fehlender Karbonatisierungswert
- unbestaetigte Karbonatisierungsangabe
- ungepruefte fachliche Markierung

Ergebnis:

- Review-Bericht
- Ampel oder Status je Schritt

### Schritt 18: Export fuer Prototyp

Aufgabe:

Der Prototyp gibt die bearbeiteten Daten aus.

Pflichtausgaben:

- Mastertabelle als `.xlsx`
- Bildzuordnung als `.xlsx`, `.csv` oder `.json`
- Review-Bericht als Markdown

Optionale spaetere Ausgaben:

- Word-Dokument
- LaTeX-Datei
- PDF

Ergebnis:

- pruefbares Exportpaket ohne Anspruch auf finales Gutachten

## 7. Web-App-Konzept fuer Version 1

### 7.1 Navigation

Die lokale Webseite soll eine klare Schritt-Navigation haben:

1. Projekt
2. Dateien
3. Laborwerte
4. Vor-Ort-Werte
5. Gruppierung
6. Mastertabelle
7. Bilder
8. Karbonatisierung
9. Review
10. Export

Jeder Schritt zeigt:

- Eingaben
- automatische Vorschlaege
- manuelle Korrektur
- Status
- naechste Aktion

### 7.2 Projektseite

Funktionen:

- Projekt anlegen
- Projekt oeffnen
- Stammdaten bearbeiten
- Fortschritt sehen

### 7.3 Datei-Seite

Funktionen:

- Dateien hinzufuegen
- Datei-Inventar anzeigen
- Kategorie bestaetigen
- Originalschutz sichtbar machen

### 7.4 Laborwerte-Seite

Funktionen:

- Labor-Excel auswaehlen
- erkannte Proben anzeigen
- Vorschautabelle pruefen
- Werte manuell korrigieren
- bereinigte Tabelle speichern

Wichtig:

- `> 6,00` bleibt Textanzeige.
- Zellquelle bleibt sichtbar.

### 7.5 Vor-Ort-Werte-Seite

Funktionen:

- Tabelle direkt eingeben
- Werte einfuegen aus Zwischenablage
- spaeter optional Bild/OCR-Ansicht
- PXX-Normalisierung anzeigen
- fehlende Hoehen als `-` setzen

### 7.6 Gruppierungs-Seite

Funktionen:

- Systemvorschlag anzeigen
- paarweise Gruppierung anbieten
- Gruppen per Drag-and-drop oder Auswahl korrigieren
- Einzelprobe erlauben
- Sonderfall markieren

### 7.7 Mastertabelle-Seite

Funktionen:

- kombinierte Tabelle anzeigen
- Filter fuer offene Felder
- direkte Korrektur
- Status je Probe
- Export als Excel

### 7.8 Bild-Seite

Funktionen:

- Bilder chronologisch anzeigen
- EXIF/Dateiname anzeigen
- aktueller Beprobungsstelle Bild zuordnen
- jedes Positionsbild manuell bestaetigen
- zweites Bild erlauben
- Bildtextvorschlag anzeigen

### 7.9 Karbonatisierungs-Seite

Funktionen:

- Beprobungsstelle auswaehlen
- optional Karbonatisierungsbild zuordnen
- freien Wert eingeben
- Wert auf zugehoerige Proben uebertragen
- Status setzen: offen, bestaetigt, nicht bestimmbar

Spaeter:

- KI-Vorschlag
- Messlinie
- Bild-fuer-Bild-Bewertung

### 7.10 Review-Seite

Funktionen:

- offene Pruefpunkte anzeigen
- Warnungen je Probe
- Warnungen je Beprobungsstelle
- Exportbereitschaft anzeigen
- Review-Bericht erzeugen

### 7.11 Export-Seite

Funktionen:

- Mastertabelle exportieren
- Bildzuordnung exportieren
- Review-Bericht exportieren
- spaeter Word/LaTeX/PDF vorbereiten

## 8. Automatisierungsplan

### Phase A: Prozess sichtbar und bedienbar machen

Ziel:

Der User kann jeden Schritt in der Web-App durchgehen, auch wenn einzelne
Automatiken noch einfach sind.

Umfang:

- Schritt-Navigation
- Projektstatus
- Datei-Inventar
- manuelle Tabellenpflege
- Mastertabelle
- Review

Erfolgskriterium:

Ein Gutachtenprojekt kann von Rohdateien bis Mastertabelle nachvollziehbar
gefuehrt werden.

### Phase B: Labor-Excel robuster bereinigen

Ziel:

Schlecht formatierte Labor-Excel automatisch erkennen.

Umfang:

- Probenzeile finden
- Messwertzeile finden
- Einheit finden
- Proben normalisieren
- Werte exakt uebernehmen
- Zellquellen speichern

Erfolgskriterium:

Die Referenzdatei `ExampleStreet Chloride_17-03-2025.xlsx` wird ohne manuelle
Nacharbeit in eine saubere Chloridwert-Tabelle ueberfuehrt.

### Phase C: Vor-Ort-Werte ergonomisch erfassen

Ziel:

Die haendische Eingabe wird schneller und weniger fehleranfaellig.

Umfang:

- Tabellenpaste aus Excel
- Eingabevalidierung
- automatische PXX-Normalisierung
- Warnungen bei fehlenden Pflichtwerten
- spaeter OCR-Ansicht

Erfolgskriterium:

Der User kann alle Vor-Ort-Werte schnell eintragen und sofort Fehler sehen.

### Phase D: Bildzuordnung als Kernworkflow

Ziel:

Jede Beprobungsstelle bekommt ein bestaetigtes Positionsbild.

Umfang:

- Bildimport
- chronologische Vorschlagsreihenfolge
- manuelle Bestaetigung
- Bildtextvorschlag
- zweite Bildoption

Erfolgskriterium:

Die Bildzuordnung ist vollstaendig, nachvollziehbar und exportierbar.

### Phase E: Karbonatisierung manuell sauber erfassen

Ziel:

Karbonatisierung wird vorerst ohne KI-Zwang korrekt im Datenmodell abgebildet.

Umfang:

- freie Eingabe
- Wert pro Beprobungsstelle
- Uebertragung auf Proben
- Status und Pruefhinweis

Erfolgskriterium:

Die Mastertabelle enthaelt Karbonatisierung dort, wo sie durch User/SV
eingetragen wurde.

### Phase F: Spaeterer Dokumentexport

Ziel:

Aus den strukturierten Daten entsteht spaeter ein Gutachtenentwurf.

Optionen:

- Word ueber Platzhalter
- LaTeX aus Templates
- PDF aus LaTeX

Wichtig:

Der aktuelle Prototyp soll schon Daten so strukturieren, dass beide Wege
moeglich bleiben.

## 9. Qualitaetskontrolle

Vor Export pruefen:

- Sind alle Proben im PXX-Format?
- Gibt es doppelte Probennummern?
- Sind alle Laborwerte zugeordnet oder als fehlend markiert?
- Sind `>`-Werte exakt erhalten?
- Sind Bohrtiefen vorhanden?
- Sind Hoehen vorhanden oder `-`?
- Sind Positionen uebernommen oder bewusst offen?
- Sind Gruppierungen bestaetigt?
- Hat jede Beprobungsstelle ein bestaetigtes Positionsbild?
- Sind Karbonatisierungswerte eingetragen oder offen markiert?
- Wird Orange nicht automatisch gesetzt?
- Werden rote Markierungen nur nach bestaetigter Regel gesetzt?
- Sind alle offenen fachlichen Punkte sichtbar?

## 10. Entscheidungen aus dem aktuellen Gespraech

- Version 1 priorisiert Mastertabelle und Bildzuordnung.
- Kein fertiges Word-Dokument als Pflichtziel fuer den naechsten Schritt.
- LaTeX/PDF ist langfristig interessant und soll nicht verbaut werden.
- Bilder sind meist chronologisch, muessen aber manuell bestaetigt werden.
- Jeder User bestaetigt jedes Positionsbild selbst.
- KI-Karbonatisierungsbewertung wird spaeter behandelt.
- Karbonatisierungswerte duerfen frei eingegeben werden.
- Anonymisierung ist fuer diesen Prototyp nicht Teil des Kernumfangs.
- Cloudbetrieb kommt spaeter; aktuell lokale Webseite.
- Benutzerrollen sind aktuell nicht notwendig.
- Datenschutz ist fuer den lokalen Prototyp noch kein Blocker, wird aber vor
  Cloudbetrieb neu entschieden.

## 11. Naechster sinnvoller Umsetzungsschritt

Als naechstes sollte die bestehende lokale Web-App so angepasst werden, dass sie
nicht primaer den Word-Entwurf in den Vordergrund stellt, sondern diesen Ablauf:

1. Projektdateien bestaetigen.
2. Laborwerte bereinigen.
3. Vor-Ort-Werte erfassen.
4. Proben gruppieren.
5. Mastertabelle erzeugen.
6. Positionsbilder manuell zuordnen.
7. Karbonatisierung frei erfassen.
8. Review und Export von Mastertabelle/Bildzuordnung.

Damit entsteht ein brauchbarer Arbeitsprototyp, der schon im echten Ablauf
hilft, ohne zu frueh den gesamten Gutachtenexport loesen zu muessen.
