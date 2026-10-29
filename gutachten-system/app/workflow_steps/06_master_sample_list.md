# 06 Master-Probenliste erstellen

## Ziel

Laborwerte und Vor-Ort-Werte werden ueber die Probennummer zusammengefuehrt.

## Spalten

- Proben-Nr.
- Position
- Bohrtiefe [mm]
- Hoehe [cm]
- %Cl(Zement) Masse-%
- Karbonatisierung [Tiefe in mm]
- Bewertungsvorschlag
- Farbe
- Status

## Bewertungsregeln im MVP

- Chloridwert ueber `1,0 %` ergibt `rot`.
- Chloridwert zwischen `0,2 %` und `1,0 %` braucht Karbonatisierungspruefung.
- Bei kritischer Karbonatisierung wird `orange` vorgeschlagen.
- Fehlende Werte fuehren zu `Pruefung erforderlich`.

## Ergebnis

`Master_Probenliste.xlsx` mit farblicher Markierung.
