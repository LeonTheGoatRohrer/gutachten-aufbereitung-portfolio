# Gutachten-System MVP 1

Lokale Web-App zur Vorbereitung von Gutachtenentwuerfen.

Der erste MVP deckt ab:

- Projektordner mit unveraenderten Originaldateien anlegen
- Projektdateien importieren und klassifizieren
- Labor-Excel heuristisch bereinigen
- Vor-Ort-Werte manuell erfassen
- Master-Probenliste erzeugen
- Chloridwerte farblich bewerten
- einfachen Gutachtenentwurf und Review-Bericht ausgeben
- Workflow-Schritte als Markdown-Dateien samt Pruefprompt in der App bearbeiten

## Start

```powershell
cd gutachten-system
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Falls `pip` wegen lokaler SSL-Zertifikate nicht auf PyPI zugreifen kann:

```powershell
.\.venv\Scripts\python -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

Dann im Browser oeffnen:

```text
http://127.0.0.1:8000
```

## Grundsatz

Das System erstellt einen pruefbaren Entwurf. Es ersetzt keine fachliche
Freigabe durch den Sachverstaendigen.
