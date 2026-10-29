# 00 Globale Regeln

## Ziel

Diese Regeln gelten fuer jeden Agenten und jeden Verarbeitungsschritt.

## Verbindliche Grundsaetze

- Originaldateien niemals ueberschreiben.
- Alle importierten Dateien zuerst in `00_original/` sichern.
- Messwerte niemals erfinden, interpolieren oder fachlich aufrunden.
- Unklare Werte als `Pruefung erforderlich` markieren.
- Handschriftliche Texte nur uebernehmen, wenn sie klar lesbar sind.
- Zahlen haben Vorrang vor Beschreibungstext.
- Fachliche Endbewertungen nur als Vorschlag erzeugen.
- SV-Freigabe ist fuer finale Bewertung, Schlussfolgerung und Export erforderlich.
- Word-Vorlagen nur ueber definierte Platzhalter befuellen.
- Jede automatische Aenderung im Projektprotokoll dokumentieren.

## Datenhaltung

`project_state.json` ist die fuehrende interne Statusdatei. Alle Schritte muessen
ihre Ergebnisse dort oder in einem referenzierten Ausgabedokument ablegen.
