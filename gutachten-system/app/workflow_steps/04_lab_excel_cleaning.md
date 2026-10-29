# 04 Labor-Excel bereinigen

## Ziel

Schlecht formatierte Labor-Excel-Dateien werden in eine saubere interne Tabelle umgewandelt.

## Zielfelder

- Probe
- Chloridwert als Anzeige
- Chloridwert numerisch fuer Regeln
- Einheit
- Quelle
- Sicherheit

## Vorgehen

1. Workbook mit Datenwerten lesen.
2. Querformatige Laborberichte erkennen: Proben oben, Chloridzeile darunter.
3. Klassische Tabellen erkennen: Probe und Chloridwert in Spalten.
4. Probennummern normalisieren, z. B. `P1` zu `P01`.
5. Anzeige von Laborwerten erhalten, z. B. `> 6,00`.
6. Numerische Hilfswerte nur intern fuer Bewertung ableiten.
7. Ergebnis als `clean_lab_values.xlsx` speichern.

## Ergebnis

Laborwerte sind sauber, aber nicht fachlich umgedeutet.
