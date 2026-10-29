# Gutachtenaufbereitung

A local FastAPI workflow prototype for preparing technical expert-report drafts while preserving original evidence and recording review steps.

## Implemented features

- Project creation and file/ZIP/folder import.
- File inventory and role classification.
- Heuristic laboratory-spreadsheet processing and manual field observations.
- Master-sample workflow, draft generation and review steps.
- Browser interface and workflow-step documents.

## Technology

Python, FastAPI, Jinja2, python-docx, openpyxl and local filesystem storage.

## Installation and local use

```powershell
cd gutachten-system
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/prototype`. Tests: `python -m pytest -q`. The illustration files in `examples/synthetic/` are entirely fictional and explain the expected data structure; spreadsheet/Word test inputs are generated in memory by the existing tests.

## Configuration and requirements

Python 3.11+ and local writable storage. Imported files and project state remain under the ignored local `gutachten-system/projects/` directory. Keep the application on loopback while evaluating it. No real reports, photographs, object addresses or client datasets are included in this snapshot.

## Development status and limitations

MVP with unfinished workflow stages. Heuristic cleaning and generated conclusions need human review. Drafts do not replace an expert’s professional assessment or release. Production deployment was not performed. The original private history is preserved separately because its project documents refer to a real property.

## Contribution and attribution

Leon Rohrer: workflow/application development in the existing project. Third-party framework licenses are retained. Real client reports and source evidence are not portfolio material.



## Publication notes

This portfolio copy includes project source and relevant documentation. Local credentials, private datasets, dependencies and generated build files are excluded. No deployment or paid service is configured by this publication. Existing copyright and license notices remain applicable; this publication does not introduce a new license.
