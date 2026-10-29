# 02 Dateien importieren

## Ziel

Alle erhaltenen Projektdateien werden in das Projekt uebernommen, ohne die Quelle zu veraendern.

## Eingaben

- Lokaler Quellordner
- Optional spaeter: ZIP, USB-Stick, Upload

## Vorgehen

1. Quellordner validieren.
2. Dateien rekursiv lesen.
3. Dateien nach `00_original/` kopieren.
4. Bestehende Dateien nicht ueberschreiben, sondern mit Suffix sichern.
5. Importquelle und Anzahl der Dateien im Projektstatus speichern.

## Ergebnis

Alle Originaldateien liegen im Projektordner und bleiben unveraendert.
