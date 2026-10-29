from __future__ import annotations

import html
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.templating import Jinja2Templates

from .processing import (
    accept_lab_table,
    create_export_package,
    create_mock_field_measurements,
    extract_lab_values_manual,
    generate_image_captions,
    generate_image_inventory,
    generate_lab_field_merge,
    generate_marking_proposals,
    generate_master,
    generate_position_image_assignments,
    generate_report_tables,
    generate_sample_groups,
    load_lab_preview,
    mark_field_measurements_unavailable,
    save_carbonation_values,
    save_clean_lab_table,
    save_image_captions,
    save_image_selection,
    save_position_image_assignments,
    save_field_measurements,
)
from .reporting import generate_review
from .onsite import sync_onsite_capture
from .storage import (
    APP_ROOT,
    PROJECTS_DIR,
    WORKFLOW_DIR,
    append_log,
    create_project,
    import_uploaded_files,
    import_uploaded_file,
    list_projects,
    load_state,
    resolve_project_file,
    save_state,
)
from .workflow import load_step, load_steps, save_step


app = FastAPI(title="Gutachten-System MVP 1")
app.mount("/static", StaticFiles(directory=APP_ROOT / "app" / "static"), name="static")
templates = Jinja2Templates(directory=APP_ROOT / "app" / "templates")

# Zeitpunkt des letzten Starts/Deploys - klein im Kopf angezeigt, damit nach
# einem Deploy sichtbar ist, ob der neue Stand wirklich live ist.
try:
    from zoneinfo import ZoneInfo

    _DEPLOY_TZ: Any = ZoneInfo("Europe/Vienna")
except Exception:  # pragma: no cover - Fallback ohne Zeitzonendaten
    _DEPLOY_TZ = None

DEPLOY_STAMP = datetime.now(_DEPLOY_TZ).strftime("%d.%m.%Y %H:%M")
templates.env.globals["deploy_stamp"] = DEPLOY_STAMP

# Obergrenze fuer Dateien je Projektordner-Upload (Fotoordner koennen gross sein).
MAX_FOLDER_UPLOAD_FILES = 50000

# Cookie, damit nach Tab-Schliessen das zuletzt aktive Projekt wiedergefunden wird.
LAST_PROJECT_COOKIE = "last_project_id"
LAST_PROJECT_COOKIE_MAX_AGE = 60 * 60 * 24 * 30


def _wants_json_error(request: Request) -> bool:
    # Browser-Formulare erwarten eine HTML-Fehlerseite, echte API-/AJAX-Aufrufe
    # (z. B. der Vor-Ort-Sync mit JSON-Body) weiterhin eine JSON-Antwort.
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return True
    if request.headers.get("content-type", "").startswith("application/json"):
        return True
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


@app.exception_handler(StarletteHTTPException)
async def http_exception_as_page(request: Request, exc: StarletteHTTPException):
    if _wants_json_error(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    back_url = request.headers.get("referer") or "/prototype"
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "status_code": exc.status_code,
            "detail": exc.detail or "Unbekannter Fehler.",
            "back_url": back_url,
        },
        status_code=exc.status_code,
    )

PROTOTYPE_STEPS = [
    {
        "id": "projekt",
        "number": "01",
        "title": "Projekt anlegen",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "Funktionsfaehig",
        "goal": "Ein neues lokales Gutachtenprojekt mit Basisdaten anlegen.",
        "inputs": ["Projektname", "Objektadresse", "Auftraggeber", "Besichtigungsdatum"],
        "actions": [
            "Projektordner vorbereiten",
            "Stammdaten erfassen",
            "Workflow mit allen Schritten initialisieren",
        ],
        "result": "Ein leeres, nachvollziehbares Projekt mit Statusdatei.",
    },
    {
        "id": "dateien",
        "number": "02",
        "title": "Dateien importieren",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "Funktionsfaehig",
        "goal": "Projektdateien uebernehmen, ohne Originale zu veraendern.",
        "inputs": ["Gutachten", "Labor-Excel", "Notizen", "Bildordner", "Anlagen"],
        "actions": [
            "Originale in 00_original sichern",
            "Datei-Inventar erzeugen",
            "Namenskonflikte markieren",
        ],
        "result": "Eine geschuetzte Projektablage mit Dateiuebersicht.",
    },
    {
        "id": "klassifizieren",
        "number": "03",
        "title": "Dateien klassifizieren",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "Funktionsfaehig",
        "goal": "Jede Datei einer sinnvollen Kategorie zuordnen.",
        "inputs": ["Datei-Inventar"],
        "actions": [
            "Laborwerte, Vorlage, Bilder und Anlagen erkennen",
            "Unklare Dateien sichtbar lassen",
            "Manuelle Korrektur ermoeglichen",
        ],
        "result": "Bestaetigtes Datei-Inventar als Grundlage fuer die naechsten Schritte.",
    },
    {
        "id": "laborwerte",
        "number": "04",
        "title": "Laborwerte bereinigen",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "MVP manuell",
        "goal": "Schlecht formatierte Labor-Excel in eine saubere Chloridwert-Tabelle ueberfuehren.",
        "inputs": ["Labor-Excel", "Probenbezeichnungen", "Chloridwerte", "Einheit"],
        "actions": [
            "Probenzeile erkennen",
            "Messwertzeile erkennen",
            "Werte exakt uebernehmen",
            "Zellquelle speichern",
        ],
        "result": "Bereinigte Chloridwert-Tabelle mit Anzeige- und Hilfswerten.",
    },
    {
        "id": "vor-ort",
        "number": "05",
        "title": "Vor-Ort-Werte erfassen",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "Mobile Erfassung",
        "goal": "Handschriftliche oder bereits erfasste Werte sauber digitalisieren.",
        "inputs": ["Proben-Nr.", "Position", "Bohrtiefe", "Hoehe", "Bemerkung"],
        "actions": [
            "Tabellenwerte einfuegen oder manuell erfassen",
            "Zahlen priorisieren",
            "Unlesbare Positionen offen lassen",
        ],
        "result": "Digitale Vor-Ort-Tabelle als Arbeitsgrundlage.",
    },
    {
        "id": "normalisieren",
        "number": "06",
        "title": "Proben, Bohrtiefe und Hoehe pruefen",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "CSV oder Mockdaten",
        "goal": "Probenbezeichnungen normalisieren und Vor-Ort-Werte fuer den weiteren Durchlauf pruefen.",
        "inputs": ["Originale Probenschreibweise", "Position", "Bohrtiefe [mm]", "Hoehe [cm]", "Karbonatisierung"],
        "actions": [
            "Varianten wie 1, 01, P1 und Probe 1 vereinheitlichen",
            "Originalschreibweise behalten",
            "Doppelte Nummern markieren",
            "Bohrtiefe, Hoehe und Karbonatisierung aus vorhandenen Daten uebernehmen",
            "Fehlende Werte oder Mockdaten klar markieren",
        ],
        "result": "Gepruefte Vor-Ort-Tabelle als Grundlage fuer Masterliste und Tabellen.",
    },
    {
        "id": "gruppieren",
        "number": "07",
        "title": "Proben gruppieren",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "Funktionsfaehig",
        "goal": "Proben zu Beprobungsstellen zusammenfassen.",
        "inputs": ["Position", "Probennummer", "Tiefenstufen"],
        "actions": [
            "Gleiche Positionen gruppieren",
            "Paarweise Gruppierung vorschlagen",
            "Einzelproben und Sonderfaelle erlauben",
        ],
        "result": "Bestaetigte Beprobungsstellen mit zugehoerigen Proben.",
    },
    {
        "id": "verbinden",
        "number": "08",
        "title": "Labor und Vor-Ort verbinden",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "MVP manuell",
        "goal": "Laborwerte ueber Probennummern mit Vor-Ort-Daten verbinden.",
        "inputs": ["PXX-Probenliste", "bereinigte Laborwerte", "Vor-Ort-Tabelle"],
        "actions": [
            "Match ueber Probennummer",
            "Fehlende Werte markieren",
            "Hinweise wie Eisen getroffen uebernehmen",
        ],
        "result": "Vorlaeufige Mastertabelle.",
    },
    {
        "id": "mastertabelle",
        "number": "09",
        "title": "Mastertabelle erzeugen",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "MVP manuell",
        "goal": "Alle Probeninformationen in einer zentralen Tabelle buendeln.",
        "inputs": ["Vor-Ort-Werte", "Laborwerte", "Gruppierung"],
        "actions": [
            "Probenzeilen erzeugen",
            "Status je Probe berechnen",
            "Leere Felder sichtbar machen",
        ],
        "result": "Master-Probenliste als Hauptausgabe des Prototyps.",
    },
    {
        "id": "markierung",
        "number": "10",
        "title": "Markierungen vorbereiten",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "MVP Vorschlag",
        "goal": "Sichere Bewertungsmarkierungen vorsichtig anzeigen.",
        "inputs": ["Chlorid-Anzeigewert", "numerischer Hilfswert"],
        "actions": [
            "Chlorid > 1,0 % als rot vorschlagen",
            "Orange nicht automatisch setzen",
            "Unsichere Regeln als Pruefpunkt markieren",
        ],
        "result": "Markierungsvorschlaege ohne ungepruefte Fachlogik.",
    },
    {
        "id": "bilder",
        "number": "11",
        "title": "Bilder importieren und sortieren",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "MVP Inventar",
        "goal": "Fotos chronologisch anzeigen und manuelle Reihenfolge erlauben.",
        "inputs": ["Bildordner", "EXIF-Datum", "Dateiname"],
        "actions": [
            "Bilder als Liste anzeigen",
            "Chronologische Vorschlagsreihenfolge bilden",
            "Manuelle Korrektur ermoeglichen",
        ],
        "result": "Sortierte Bildliste als Grundlage fuer Zuordnung.",
    },
    {
        "id": "positionsbilder",
        "number": "12",
        "title": "Positionsbilder zuordnen",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "MVP Vorschlag",
        "goal": "Jede Beprobungsstelle bekommt ein vom User bestaetigtes Positionsbild.",
        "inputs": ["Beprobungsstelle", "Bildliste", "Position"],
        "actions": [
            "Ein Bild pro Stelle auswaehlen",
            "Optional zweites Bild erlauben",
            "Zuordnung bestaetigen oder als unklar markieren",
        ],
        "result": "Bestaetigte Bildzuordnung je Beprobungsstelle.",
    },
    {
        "id": "bildtexte",
        "number": "13",
        "title": "Bildtexte vorbereiten",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "MVP Vorschlag",
        "goal": "Aus Probenwerten und Gruppierung editierbare Bildtexte erzeugen.",
        "inputs": ["Proben", "Position", "Bohrtiefen", "Hoehe"],
        "actions": [
            "Tiefenbereiche vorschlagen",
            "Position und Hoehe einsetzen",
            "Text manuell editierbar lassen",
        ],
        "result": "Bildtextvorschlaege fuer spaeteren Bericht.",
    },
    {
        "id": "karbonatisierung",
        "number": "14",
        "title": "Karbonatisierung erfassen",
        "status": "Spaeter mit KI",
        "implemented": True,
        "implementation_label": "MVP Nachtrag",
        "goal": "Karbonatisierungswerte pro Beprobungsstelle frei erfassen.",
        "inputs": ["Beprobungsstelle", "Karbonatisierungsbild", "freier Wert"],
        "actions": [
            "Freie Eingabe erlauben",
            "Wert auf zugehoerige Proben uebertragen",
            "Bestaetigungsstatus setzen",
        ],
        "result": "Karbonatisierung in der Mastertabelle, ohne automatische finale Bewertung.",
    },
    {
        "id": "tabellen",
        "number": "15",
        "title": "Tabellenansichten erzeugen",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "Funktionsfaehig",
        "goal": "Einfache Tabelle und End-/Mastertabelle getrennt anzeigen.",
        "inputs": ["Mastertabelle"],
        "actions": [
            "Einfache Beprobungsstellen-Tabelle erzeugen",
            "Endtabelle erzeugen",
            "Farben nur in Endtabelle verwenden",
        ],
        "result": "Klare Tabellenansichten fuer spaetere Ausgaben.",
    },
    {
        "id": "review",
        "number": "16",
        "title": "Review anzeigen",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "Funktionsfaehig",
        "goal": "Offene Punkte je Projekt sichtbar machen.",
        "inputs": ["Mastertabelle", "Bildzuordnung", "Statusfelder"],
        "actions": [
            "Fehlende Werte listen",
            "Unbestaetigte Zuordnungen zeigen",
            "Exportbereitschaft anzeigen",
        ],
        "result": "Pruefbericht fuer die weitere Bearbeitung.",
    },
    {
        "id": "export",
        "number": "17",
        "title": "Export fuer Prototyp",
        "status": "Konzept",
        "implemented": True,
        "implementation_label": "MVP Paket",
        "goal": "Mastertabelle, Bildzuordnung und Review exportierbar machen.",
        "inputs": ["Mastertabelle", "Bildzuordnung", "Review"],
        "actions": [
            "Excel-Export vorbereiten",
            "Bildzuordnung als Tabelle ausgeben",
            "Review-Bericht erzeugen",
        ],
        "result": "Pruefbares Exportpaket ohne finalen Gutachtenanspruch.",
    },
]

CLASSIFICATION_ROLES = [
    {
        "key": "template_file",
        "title": "Gutachtenvorlage",
        "hint": "Word-Vorlage, in die spaeter Tabellen, Bilder und Texte eingefuegt werden.",
        "accepts": ".docx",
        "multiple": False,
    },
    {
        "key": "lab_file",
        "title": "Labor-Excel / Chloridwerte",
        "hint": "Unformatierte oder schlecht formatierte Labor-Datei mit Chloridwerten.",
        "accepts": ".xlsx / .xls / .csv",
        "multiple": False,
    },
    {
        "key": "field_notes_file",
        "title": "Handschriftliche Beprobungstabelle",
        "hint": "Vor-Ort-Tabelle mit Probennummern, Positionen, Bohrtiefen und Hoehen.",
        "accepts": "Bild / PDF",
        "multiple": False,
    },
    {
        "key": "image_folder",
        "title": "Bildordner / Fotodokumentation",
        "hint": "Chronologisch sortierte Baustellenbilder fuer Beprobungsstellen und Karbonatisierung.",
        "accepts": "Ordner mit Bildern",
        "multiple": False,
    },
    {
        "key": "attachments_folder",
        "title": "Anlagen / Zusatzunterlagen",
        "hint": "Laborbefund, Plaene, Orthofoto, Fotodokumentation und sonstige Anlagen.",
        "accepts": "Datei / Ordner",
        "multiple": True,
    },
]

REQUIRED_CLASSIFICATION_KEYS = {role["key"] for role in CLASSIFICATION_ROLES}


def project_query(project_id: str | None) -> str:
    return f"?project_id={project_id}" if project_id else ""


def parse_state_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def start_statistics(projects: list[dict[str, Any]]) -> dict[str, Any]:
    days_by_key: dict[str, dict[str, Any]] = {}

    def project_metric(project: dict[str, Any], key: str) -> int:
        value = project.get(key)
        return len(value) if isinstance(value, (dict, list)) else 0

    def day_bucket(day: datetime) -> dict[str, Any]:
        key = day.date().isoformat()
        if key not in days_by_key:
            days_by_key[key] = {
                "date_key": key,
                "label": day.strftime("%d.%m.%Y"),
                "short_label": day.strftime("%d.%m."),
                "event_count": 0,
                "project_ids": set(),
                "projects": {},
                "logs": [],
                "files": 0,
                "lab_values": 0,
                "master_samples": 0,
                "outputs": 0,
            }
        return days_by_key[key]

    for project in projects:
        project_id = str(project.get("id") or project.get("_id") or "")
        if not project_id:
            continue
        project_name = project.get("project", {}).get("name") or project_id
        project_summary = {
            "id": project_id,
            "name": project_name,
            "status": project.get("status") or "ohne Status",
            "updated_at": project.get("updated_at") or "",
            "file_count": project_metric(project, "file_inventory"),
            "lab_value_count": project_metric(project, "lab_values"),
            "master_sample_count": project_metric(project, "master_samples"),
            "output_count": project_metric(project, "outputs"),
        }

        log_entries = project.get("log") if isinstance(project.get("log"), list) else []
        dated_logs = []
        for entry in log_entries:
            if not isinstance(entry, dict):
                continue
            logged_at = parse_state_datetime(entry.get("time"))
            if logged_at:
                dated_logs.append((logged_at, str(entry.get("message") or "")))

        if not dated_logs:
            fallback_date = parse_state_datetime(project.get("updated_at")) or parse_state_datetime(project.get("created_at"))
            if fallback_date:
                dated_logs.append((fallback_date, "Projektstatus aktualisiert."))

        for logged_at, message in dated_logs:
            bucket = day_bucket(logged_at)
            if project_id not in bucket["project_ids"]:
                bucket["project_ids"].add(project_id)
                bucket["projects"][project_id] = project_summary
                bucket["files"] += project_summary["file_count"]
                bucket["lab_values"] += project_summary["lab_value_count"]
                bucket["master_samples"] += project_summary["master_sample_count"]
                bucket["outputs"] += project_summary["output_count"]
            bucket["event_count"] += 1
            if message:
                bucket["logs"].append(
                    {
                        "time": logged_at.strftime("%H:%M"),
                        "project": project_name,
                        "message": message,
                    }
                )

    days = sorted(days_by_key.values(), key=lambda item: item["date_key"], reverse=True)
    max_events = max((day["event_count"] for day in days), default=1)
    for day in days:
        day["project_count"] = len(day["project_ids"])
        day["height"] = max(12, round((day["event_count"] / max_events) * 100)) if day["event_count"] else 12
        day["projects"] = sorted(day["projects"].values(), key=lambda item: item["name"].lower())
        day["logs"] = sorted(day["logs"], key=lambda item: item["time"], reverse=True)[:8]
        del day["project_ids"]

    return {
        "total_projects": len(projects),
        "total_files": sum(project_metric(project, "file_inventory") for project in projects),
        "total_lab_values": sum(project_metric(project, "lab_values") for project in projects),
        "total_outputs": sum(project_metric(project, "outputs") for project in projects),
        "days": days[:14],
    }


def render_review_markdown(markdown: str) -> str:
    lines: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            lines.append("</ul>")
            in_list = False

    def render_inline(value: str) -> str:
        escaped = html.escape(value)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        return escaped

    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            close_list()
            continue
        if stripped.startswith("### "):
            close_list()
            lines.append(f"<h3>{render_inline(stripped[4:])}</h3>")
            continue
        if stripped.startswith("## "):
            close_list()
            lines.append(f"<h2>{render_inline(stripped[3:])}</h2>")
            continue
        if stripped.startswith("# "):
            close_list()
            lines.append(f"<h1>{render_inline(stripped[2:])}</h1>")
            continue
        if stripped.startswith("- "):
            if not in_list:
                lines.append("<ul>")
                in_list = True
            item = stripped[2:]
            status = item.upper()
            item_class = ""
            if status.startswith("FEHLER"):
                item_class = ' class="review-item-error"'
            elif status.startswith("WARNUNG"):
                item_class = ' class="review-item-warning"'
            elif status.startswith("OK"):
                item_class = ' class="review-item-ok"'
            elif status.startswith("OFFEN"):
                item_class = ' class="review-item-open"'
            lines.append(f"<li{item_class}>{render_inline(item)}</li>")
            continue
        close_list()
        lines.append(f"<p>{render_inline(stripped)}</p>")

    close_list()
    return "\n".join(lines)


def review_preview_for_project(state: dict[str, Any]) -> dict[str, Any] | None:
    review_path = state.get("outputs", {}).get("review_report")
    if not review_path:
        return None
    try:
        file_path = resolve_project_file(state["id"], review_path)
    except (KeyError, ValueError):
        return {"path": review_path, "html": "", "available": False}
    if not file_path.exists() or not file_path.is_file():
        return {"path": review_path, "html": "", "available": False}
    markdown = file_path.read_text(encoding="utf-8")
    return {
        "path": review_path,
        "html": render_review_markdown(markdown),
        "available": True,
    }


def _selected_parts(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def classification_complete(state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    selected_files = state.get("selected_files", {})
    return all(_selected_parts(selected_files.get(key, "")) for key in REQUIRED_CLASSIFICATION_KEYS)


def field_step_ready(state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    return bool(state.get("field_measurements")) or bool(state.get("field_measurements_unavailable"))


def workflow_step_states(state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    outputs = state.get("outputs", {}) if state else {}
    has_project = bool(state)
    has_inventory = bool(state and state.get("file_inventory"))
    has_lab_values = bool(state and state.get("lab_values"))
    has_clean_lab_output = bool(outputs.get("clean_lab_values"))
    has_field_values = bool(state and state.get("field_measurements"))
    field_unavailable = bool(state and state.get("field_measurements_unavailable"))
    field_ready = field_step_ready(state)
    has_groups = bool(state and state.get("sample_groups"))
    has_merge = bool(state and state.get("lab_field_merge"))
    has_master = bool(state and state.get("master_samples"))
    classified = classification_complete(state)
    has_selected_images = bool(state and state.get("selected_image_ids"))

    raw_states: dict[str, tuple[bool, bool, str, list[str]]] = {
        "projekt": (has_project, True, "Projektstammdaten anlegen", []),
        "dateien": (has_inventory, True, "Dateien oder Projektordner importieren", []),
        "klassifizieren": (
            classified,
            has_inventory,
            "Pflichtdateien zuordnen",
            [] if has_inventory else ["Zuerst in Schritt 2 Dateien importieren."],
        ),
        "laborwerte": (
            has_clean_lab_output,
            classified,
            "Laborwerte erzeugen, akzeptieren und in Output speichern",
            [] if classified else ["Zuerst alle Pflichtdateien in Schritt 3 zuordnen."],
        ),
        "vor-ort": (
            field_ready,
            has_lab_values or has_clean_lab_output,
            "Vor-Ort-Daten erfassen, importieren oder bewusst als fehlend markieren",
            [] if (has_lab_values or has_clean_lab_output) else ["Zuerst Laborwerte in Schritt 4 erzeugen."],
        ),
        "normalisieren": (
            field_ready,
            field_ready,
            "Vor-Ort-Werte pruefen oder nachtragen",
            [] if field_ready else ["Zuerst Schritt 5 abschliessen."],
        ),
        "gruppieren": (
            has_groups or field_unavailable,
            has_field_values,
            "Beprobungsstellen aus Vor-Ort-Werten vorschlagen",
            [] if has_field_values else ["Gruppierung braucht echte oder Mock-Vor-Ort-Werte."],
        ),
        "verbinden": (
            has_merge,
            has_lab_values and field_ready,
            "Labor- und Vor-Ort-Daten verbinden",
            [] if (has_lab_values and field_ready) else ["Laborwerte und Vor-Ort-Status muessen vorhanden sein."],
        ),
        "mastertabelle": (
            has_master,
            has_merge or (has_lab_values and field_unavailable),
            "Master-Probenliste erzeugen",
            [] if (has_merge or (has_lab_values and field_unavailable)) else ["Zuerst Schritt 8 ausfuehren."],
        ),
        "markierung": (
            bool(state and state.get("marking_proposals")),
            has_master,
            "Markierungsvorschlaege erzeugen",
            [] if has_master else ["Zuerst die Master-Probenliste erzeugen."],
        ),
        "bilder": (
            has_selected_images,
            has_inventory,
            "Bildinventar pruefen und Gutachtenbilder auswaehlen",
            [] if has_inventory else ["Zuerst Bilder oder Projektordner importieren."],
        ),
        "positionsbilder": (
            bool(state and state.get("position_image_assignments")),
            has_groups and has_selected_images,
            "Positionsbilder je Beprobungsstelle zuordnen",
            [] if (has_groups and has_selected_images) else ["Gruppierung und ausgewaehlte Gutachtenbilder muessen vorhanden sein."],
        ),
        "bildtexte": (
            bool(state and state.get("image_captions")),
            bool(state and state.get("position_image_assignments")),
            "Bildtexte manuell verfassen",
            [] if state and state.get("position_image_assignments") else ["Zuerst Positionsbilder in Schritt 12 zuordnen."],
        ),
        "karbonatisierung": (
            bool(state and state.get("carbonation_text")),
            field_ready,
            "Karbonatisierung optional nachtragen",
            [] if field_ready else ["Zuerst Vor-Ort-Status abschliessen."],
        ),
        "tabellen": (
            bool(outputs.get("report_tables")),
            has_master,
            "Gutachtentabellen erzeugen",
            [] if has_master else ["Zuerst die Master-Probenliste erzeugen."],
        ),
        "review": (
            bool(outputs.get("review_report")),
            has_master,
            "Review-Bericht erzeugen",
            [] if has_master else ["Zuerst die Master-Probenliste erzeugen."],
        ),
        "export": (
            bool(outputs.get("export_package")),
            bool(outputs),
            "Output-Paket erzeugen",
            [] if outputs else ["Zuerst mindestens eine Ausgabe erzeugen."],
        ),
    }

    states: dict[str, dict[str, Any]] = {}
    for step in PROTOTYPE_STEPS:
        done, unlocked, action, missing = raw_states.get(step["id"], (False, has_project, step["goal"], []))
        label = "Erledigt" if done else "Bereit" if unlocked else "Fehlt"
        states[step["id"]] = {
            "done": done,
            "unlocked": unlocked,
            "label": label,
            "action": action,
            "missing": missing,
        }
    return states


def validate_classification_paths(state: dict[str, Any], values: dict[str, str]) -> None:
    available_paths = {item["path"] for item in inventory_tree(state.get("file_inventory", []))}
    unknown_paths = [
        part
        for value in values.values()
        for part in _selected_parts(value)
        if part not in available_paths
    ]
    if unknown_paths:
        unknown = ", ".join(unknown_paths[:3])
        raise HTTPException(status_code=400, detail=f"Unbekannte Datei- oder Ordnerauswahl: {unknown}")


def prototype_context(step_id: str | None = None, project_id: str | None = None) -> dict:
    selected = next((step for step in PROTOTYPE_STEPS if step["id"] == step_id), PROTOTYPE_STEPS[0])
    selected_index = PROTOTYPE_STEPS.index(selected)
    previous_step = PROTOTYPE_STEPS[selected_index - 1] if selected_index > 0 else None
    next_step = PROTOTYPE_STEPS[selected_index + 1] if selected_index < len(PROTOTYPE_STEPS) - 1 else None
    selected_project = None
    if project_id:
        try:
            selected_project = load_state(project_id)
        except FileNotFoundError:
            selected_project = None
    visible_projects = [selected_project] if selected_project else []
    step_states = workflow_step_states(selected_project)
    return {
        "prototype_steps": PROTOTYPE_STEPS,
        "selected_step": selected,
        "selected_step_state": step_states[selected["id"]],
        "previous_step": previous_step,
        "next_step": next_step,
        "next_step_state": step_states[next_step["id"]] if next_step else None,
        "step_states": step_states,
        "workflow_progress": {
            "current": selected_index + 1,
            "total": len(PROTOTYPE_STEPS),
            "percent": round(((selected_index + 1) / len(PROTOTYPE_STEPS)) * 100),
        },
        "projects": visible_projects,
        "project_query": project_query(selected_project.get("id") if selected_project else None),
        "classification_roles": CLASSIFICATION_ROLES,
    }


def inventory_tree(inventory: list[dict]) -> list[dict]:
    tree_items: list[dict] = []
    seen_dirs: set[str] = set()
    for item in sorted(inventory, key=lambda entry: entry.get("path", "").lower()):
        path = item.get("path", "")
        parts = Path(path).parts
        for depth in range(1, max(len(parts), 1)):
            directory = Path(*parts[:depth]).as_posix()
            if directory in seen_dirs:
                continue
            seen_dirs.add(directory)
            tree_items.append(
                {
                    "type": "dir",
                    "name": parts[depth - 1],
                    "path": directory,
                    "depth": depth - 1,
                }
            )
        tree_items.append(
            {
                "type": "file",
                "name": item.get("name", Path(path).name),
                "path": path,
                "depth": max(len(parts) - 1, 0),
                "category": item.get("category", ""),
                "size": item.get("size", 0),
                "extension": item.get("extension", ""),
            }
        )
    return tree_items


def prototype_project_context(
    project_id: str | None,
    sheet_name: str | None = None,
    expanded_preview: bool = False,
) -> dict:
    if not project_id:
        return {"selected_project": None, "selected_project_tree": [], "project_query": "", "lab_preview": None}
    try:
        state = load_state(project_id)
    except FileNotFoundError:
        return {"selected_project": None, "selected_project_tree": [], "project_query": "", "lab_preview": None}
    lab_file = state.get("selected_files", {}).get("lab_file", "")
    lab_preview = None
    if lab_file:
        try:
            # Standardvorschau bleibt klein (40x20); "Mehr laden" erweitert auf
            # den Bereich, den auch die manuelle Extraktion lesen kann.
            max_rows, max_cols = (200, 40) if expanded_preview else (40, 20)
            lab_preview = load_lab_preview(project_id, lab_file, sheet_name, max_rows=max_rows, max_cols=max_cols)
        except Exception as exc:
            lab_preview = {
                "supported": False,
                "source": lab_file,
                "sheets": [],
                "selected_sheet": "",
                "headers": [],
                "rows": [],
                "warnings": [str(exc)],
            }
    caption_rows = image_caption_rows(state)
    caption_done = sum(1 for row in caption_rows if str(row.get("caption", "")).strip())
    return {
        "selected_project": state,
        "selected_project_tree": inventory_tree(state.get("file_inventory", [])),
        "project_query": project_query(state.get("id")),
        "lab_preview": lab_preview,
        "lab_preview_expanded": expanded_preview,
        "image_caption_rows": caption_rows,
        "image_caption_summary": {
            "done": caption_done,
            "missing": len(caption_rows) - caption_done,
            "total": len(caption_rows),
        },
        "selected_report_images": selected_report_images(state),
        "position_assignment_by_group": position_assignment_by_group(state),
        "review_preview": review_preview_for_project(state),
    }


def selected_report_images(state: dict[str, Any]) -> list[dict[str, Any]]:
    selected_ids = set(state.get("selected_image_ids", []))
    return [
        image
        for image in state.get("image_inventory", [])
        if image.get("use_in_report") or image.get("image_id") in selected_ids
    ]


def _assignment_values(item: dict[str, Any], list_key: str, fallback_key: str, separator: str) -> list[str]:
    values = item.get(list_key)
    if isinstance(values, list):
        return [str(value).strip() for value in values if str(value).strip()]
    fallback = str(item.get(fallback_key, "")).strip()
    return [part.strip() for part in fallback.split(separator) if part.strip()]


def assignment_image_ids(item: dict[str, Any]) -> list[str]:
    return _assignment_values(item, "image_ids", "image_id", ",")


def assignment_image_paths(item: dict[str, Any]) -> list[str]:
    return _assignment_values(item, "image_paths", "image_path", ";")


def position_assignment_by_group(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assignments: dict[str, dict[str, Any]] = {}
    for item in state.get("position_image_assignments", []):
        group_id = item.get("group_id")
        if not group_id:
            continue
        normalized = dict(item)
        normalized["image_ids"] = assignment_image_ids(item)
        normalized["image_paths"] = assignment_image_paths(item)
        assignments[group_id] = normalized
    return assignments


def image_caption_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    captions_by_group = {
        item.get("group_id"): item
        for item in state.get("image_captions", [])
        if item.get("group_id")
    }
    captions_by_pair = {
        (item.get("group_id"), item.get("image_id")): item
        for item in state.get("image_captions", [])
        if item.get("group_id")
    }
    rows: list[dict[str, Any]] = []
    for item in state.get("position_image_assignments", []):
        if not item.get("group_id"):
            continue
        image_ids = assignment_image_ids(item)
        image_paths = assignment_image_paths(item)
        if not image_paths:
            caption = captions_by_group.get(item.get("group_id"), {})
            rows.append(
                {
                    "group_id": item.get("group_id", ""),
                    "position": item.get("position", ""),
                    "probes": item.get("probes", ""),
                    "image_id": "",
                    "image_path": "",
                    "caption": caption.get("caption", ""),
                    "status": "Bildzuordnung offen",
                }
            )
            continue
        for index, image_path in enumerate(image_paths):
            image_id = image_ids[index] if index < len(image_ids) else ""
            caption = captions_by_pair.get((item.get("group_id"), image_id), captions_by_group.get(item.get("group_id"), {}))
            rows.append(
                {
                    "group_id": item.get("group_id", ""),
                    "position": item.get("position", ""),
                    "probes": item.get("probes", ""),
                    "image_id": image_id,
                    "image_path": image_path,
                    "caption": caption.get("caption", ""),
                    "status": caption.get("status") or "Text fehlt",
                }
            )
    return rows


def render_prototype(request: Request, step_id: str | None = None) -> HTMLResponse:
    # Ohne project_id in der URL wird das zuletzt aktive Projekt aus dem Cookie
    # weiterverwendet, damit ein geschlossener Tab kein "verlorenes" Projekt erzeugt.
    project_id = request.query_params.get("project_id") or request.cookies.get(LAST_PROJECT_COOKIE)
    all_projects = list_projects()
    context = {
        "request": request,
        **prototype_context(step_id, project_id),
        **prototype_project_context(
            project_id,
            request.query_params.get("sheet_name"),
            expanded_preview=request.query_params.get("preview") == "voll",
        ),
        "all_projects": all_projects,
        "start_statistics": start_statistics(all_projects),
    }
    response = templates.TemplateResponse("prototype.html", context)
    selected = context.get("selected_project")
    if selected:
        response.set_cookie(LAST_PROJECT_COOKIE, selected["id"], max_age=LAST_PROJECT_COOKIE_MAX_AGE)
    return response


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return render_prototype(request)


@app.get("/prototype", response_class=HTMLResponse)
def prototype_page(request: Request) -> HTMLResponse:
    return render_prototype(request)


@app.post("/prototype/create-project")
def prototype_create_project_route(
    project_name: Annotated[str, Form()] = "",
    object_address: Annotated[str, Form()] = "",
    client: Annotated[str, Form()] = "",
    inspection_date: Annotated[str, Form()] = "",
    expert: Annotated[str, Form()] = "",
    case_worker: Annotated[str, Form()] = "",
    object_type: Annotated[str, Form()] = "",
) -> RedirectResponse:
    if not project_name.strip():
        raise HTTPException(status_code=400, detail="Bitte einen Projektnamen eintragen.")
    state = create_project(
        {
            "project_name": project_name,
            "object_address": object_address,
            "client": client,
            "inspection_date": inspection_date,
            "expert": expert,
            "case_worker": case_worker,
            "object_type": object_type,
        }
    )
    return RedirectResponse(f"/prototype/dateien?project_id={state['id']}&saved=1#workflow", status_code=303)


@app.post("/prototype/classify")
def prototype_classify_route(
    project_id: Annotated[str, Form()],
    lab_file: Annotated[str, Form()] = "",
    field_notes_file: Annotated[str, Form()] = "",
    template_file: Annotated[str, Form()] = "",
    image_folder: Annotated[str, Form()] = "",
    attachments_folder: Annotated[str, Form()] = "",
) -> RedirectResponse:
    state = load_state(project_id)
    selected_files = state.setdefault("selected_files", {})
    values = {
        "lab_file": lab_file,
        "field_notes_file": field_notes_file,
        "template_file": template_file,
        "image_folder": image_folder,
        "attachments_folder": attachments_folder,
    }
    missing = [
        key
        for key in REQUIRED_CLASSIFICATION_KEYS
        if not any(part.strip() for part in values.get(key, "").splitlines())
    ]
    if missing:
        raise HTTPException(status_code=400, detail="Bitte zuerst alle wichtigen Dateien und Ordner zuordnen.")
    validate_classification_paths(state, values)
    for key, value in values.items():
        selected_files[key] = "\n".join(part.strip() for part in value.splitlines() if part.strip())
    state["status"] = "Dateien klassifiziert"
    assigned = sum(1 for value in values.values() if any(part.strip() for part in value.splitlines()))
    append_log(state, f"Dateien klassifiziert: {assigned} wichtige Zuordnungen gespeichert.")
    save_state(project_id, state)
    return RedirectResponse(f"/prototype/laborwerte?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/laborwerte/manual")
def prototype_lab_manual_route(
    project_id: Annotated[str, Form()],
    lab_file: Annotated[str, Form()],
    sheet_name: Annotated[str, Form()],
    sample_row: Annotated[int, Form()],
    value_row: Annotated[int, Form()],
    unit: Annotated[str, Form()] = "Masse-%",
    first_col: Annotated[str, Form()] = "",
    last_col: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        extract_lab_values_manual(
            project_id=project_id,
            lab_relative_path=lab_file,
            sheet_name=sheet_name,
            sample_row=sample_row,
            value_row=value_row,
            unit=unit,
            first_col=first_col,
            last_col=last_col,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/laborwerte?project_id={project_id}&sheet_name={sheet_name}&saved=1#workflow", status_code=303)


@app.post("/prototype/laborwerte/accept")
def prototype_lab_accept_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        accept_lab_table(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/laborwerte?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/laborwerte/save-table")
def prototype_lab_save_table_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        save_clean_lab_table(project_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/laborwerte?project_id={project_id}&saved=1#workflow", status_code=303)


@app.get("/prototype/onsite", response_class=HTMLResponse)
def prototype_onsite_page(request: Request) -> HTMLResponse:
    project_id = request.query_params.get("project_id")
    project_name = ""
    if project_id:
        try:
            state = load_state(project_id)
            project_name = state.get("project", {}).get("name") or project_id
        except FileNotFoundError:
            project_id = None
    return templates.TemplateResponse(
        "onsite_capture.html",
        {
            "request": request,
            "project_id": project_id or "",
            "project_name": project_name,
            "sync_url": f"/prototype/onsite/{project_id}/sync" if project_id else "",
            "back_url": f"/prototype/vor-ort?project_id={project_id}" if project_id else "/prototype/vor-ort",
        },
    )


@app.post("/prototype/onsite/{project_id}/sync")
def prototype_onsite_sync_route(project_id: str, payload: Annotated[dict, Body(...)]) -> JSONResponse:
    try:
        result = sync_onsite_capture(project_id, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except Exception as exc:  # defensive: Sync darf die Vor-Ort-Daten nie verlieren
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


@app.post("/prototype/vor-ort/skip")
def prototype_field_skip_route(
    project_id: Annotated[str, Form()],
    reason: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        mark_field_measurements_unavailable(project_id, reason)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    # Wie Mockdaten und CSV-Import: Nach der erledigten Aktion geht es
    # einheitlich zum naechsten sinnvollen Schritt 6 weiter.
    return RedirectResponse(f"/prototype/normalisieren?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/vor-ort/import")
def prototype_field_import_route(
    project_id: Annotated[str, Form()],
    field_text: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        save_field_measurements(project_id, field_text)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    return RedirectResponse(f"/prototype/normalisieren?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/vor-ort/mock")
def prototype_field_mock_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        create_mock_field_measurements(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    return RedirectResponse(f"/prototype/normalisieren?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/master/generate")
def prototype_master_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        generate_master(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    return RedirectResponse(f"/prototype/mastertabelle?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/gruppieren/generate")
def prototype_sample_groups_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        generate_sample_groups(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/gruppieren?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/verbinden/generate")
def prototype_lab_field_merge_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        generate_lab_field_merge(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/verbinden?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/markierung/generate")
def prototype_marking_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        generate_marking_proposals(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/markierung?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/bilder/generate")
def prototype_image_inventory_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        generate_image_inventory(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    return RedirectResponse(f"/prototype/bilder?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/bilder/select")
async def prototype_image_select_route(request: Request) -> RedirectResponse:
    form = await request.form()
    project_id = str(form.get("project_id", ""))
    selected_image_ids = [str(value) for value in form.getlist("selected_image_ids")]
    try:
        save_image_selection(project_id, selected_image_ids)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    return RedirectResponse(f"/prototype/bilder?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/positionsbilder/generate")
def prototype_position_images_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        generate_position_image_assignments(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/positionsbilder?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/positionsbilder/save")
async def prototype_position_images_save_route(request: Request) -> RedirectResponse:
    form = await request.form()
    project_id = str(form.get("project_id", ""))
    target_group_id = str(form.get("save_group", "")).strip() or None
    images_by_group: dict[str, list[str]] = {}
    for key in form.keys():
        if key.startswith("image__"):
            images_by_group[key.removeprefix("image__")] = [str(value) for value in form.getlist(key)]
    try:
        save_position_image_assignments(project_id, images_by_group, target_group_id=target_group_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/positionsbilder?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/bildtexte/generate")
def prototype_image_captions_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        generate_image_captions(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/bildtexte?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/bildtexte/save")
async def prototype_image_captions_save_route(request: Request) -> RedirectResponse:
    form = await request.form()
    project_id = str(form.get("project_id", ""))
    captions_by_key = {
        key.removeprefix("caption__"): str(value)
        for key, value in form.items()
        if key.startswith("caption__")
    }
    try:
        save_image_captions(project_id, captions_by_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/bildtexte?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/karbonatisierung/import")
def prototype_carbonation_import_route(
    project_id: Annotated[str, Form()],
    carbonation_text: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        save_carbonation_values(project_id, carbonation_text)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/karbonatisierung?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/tabellen/generate")
def prototype_tables_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        generate_report_tables(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/tabellen?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/review/generate")
def prototype_review_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        generate_review(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    return RedirectResponse(f"/prototype/review?project_id={project_id}&saved=1#workflow", status_code=303)


@app.post("/prototype/export/generate")
def prototype_export_generate_route(project_id: Annotated[str, Form()]) -> RedirectResponse:
    try:
        create_export_package(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/prototype/export?project_id={project_id}&saved=1#workflow", status_code=303)


def resolve_upload_project(project_id: str, fallback_name: str) -> dict[str, Any]:
    # Uploads sollen im aktiven Projekt landen (Stammdaten bleiben erhalten).
    # Nur ohne aktives Projekt wird wie bisher ein neues angelegt.
    cleaned = (project_id or "").strip()
    if cleaned:
        try:
            return load_state(cleaned)
        except FileNotFoundError:
            pass
    return create_project({"project_name": fallback_name})


@app.post("/prototype/upload")
def prototype_upload_route(
    gutachten_file: Annotated[UploadFile, File()],
    project_id: Annotated[str, Form()] = "",
) -> RedirectResponse:
    if not gutachten_file.filename:
        raise HTTPException(status_code=400, detail="Bitte eine Gutachten- oder ZIP-Datei auswaehlen.")

    suffix = Path(gutachten_file.filename).suffix.lower()
    allowed_suffixes = {".zip", ".doc", ".docx", ".pdf"}
    if suffix not in allowed_suffixes:
        raise HTTPException(
            status_code=400,
            detail="Erlaubt sind aktuell ZIP, DOC, DOCX und PDF.",
        )

    state = resolve_upload_project(project_id, Path(gutachten_file.filename).stem)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            shutil.copyfileobj(gutachten_file.file, temp_file)
            temp_path = Path(temp_file.name)
        import_uploaded_file(state["id"], temp_path, gutachten_file.filename)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Die ZIP-Datei konnte nicht gelesen werden.") from exc
    finally:
        gutachten_file.file.close()
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    return RedirectResponse(f"/prototype/klassifizieren?project_id={state['id']}&saved=1#workflow", status_code=303)


@app.post("/prototype/upload-folder")
async def prototype_upload_folder_route(request: Request) -> RedirectResponse:
    # Ganze Projektordner koennen tausende Dateien (vor allem Fotos) enthalten.
    # Starlette begrenzt Multipart-Uploads standardmaessig auf 1000 Dateien, was
    # bei echten Gutachtenordnern zu einem stillen HTTP-400 fuehrt. Darum wird das
    # Formular hier bewusst mit hoeheren Grenzen geparst.
    form = await request.form(max_files=MAX_FOLDER_UPLOAD_FILES, max_fields=MAX_FOLDER_UPLOAD_FILES)
    # request.form() liefert Starlettes UploadFile (Basisklasse von fastapi.UploadFile).
    project_files = [item for item in form.getlist("project_files") if isinstance(item, StarletteUploadFile)]
    if not project_files:
        raise HTTPException(status_code=400, detail="Bitte einen Projektordner auswaehlen.")

    project_id = str(form.get("project_id", ""))
    first_filename = project_files[0].filename or "projektordner"
    first_parts = Path(first_filename.replace("\\", "/")).parts
    project_name = first_parts[0] if len(first_parts) > 1 else Path(first_filename).stem or "projektordner"

    temp_dir = Path(tempfile.mkdtemp(prefix="gutachten-folder-upload-"))
    saved_files: list[tuple[Path, str]] = []
    try:
        for index, upload in enumerate(project_files):
            if not upload.filename:
                continue
            suffix = Path(upload.filename).suffix
            temp_path = temp_dir / f"upload_{index}{suffix}"
            with temp_path.open("wb") as temp_file:
                shutil.copyfileobj(upload.file, temp_file)
            saved_files.append((temp_path, upload.filename))
        if not saved_files:
            raise HTTPException(status_code=400, detail="Der ausgewaehlte Projektordner enthaelt keine importierbaren Dateien.")
        state = resolve_upload_project(project_id, project_name)
        import_uploaded_files(state["id"], saved_files)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Eine ZIP-Datei im Upload konnte nicht gelesen werden.") from exc
    finally:
        for upload in project_files:
            upload.file.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    return RedirectResponse(f"/prototype/klassifizieren?project_id={state['id']}&saved=1#workflow", status_code=303)


@app.post("/prototype/import-folder-path")
def prototype_import_folder_path_route(
    folder_path: Annotated[str, Form()],
    project_id: Annotated[str, Form()] = "",
) -> RedirectResponse:
    # Lokaler Direktimport: Die App laeuft auf demselben Rechner wie die Daten,
    # darum kopiert das Backend den Ordner direkt von der Platte statt ihn als
    # Multipart-Upload durch den Browser zu schicken. Das ist bei grossen
    # Fotoordnern um Groessenordnungen schneller (Sekunden statt Minuten).
    raw = (folder_path or "").strip().strip('"')
    if not raw:
        raise HTTPException(status_code=400, detail="Bitte einen Ordnerpfad eingeben.")

    folder = Path(raw).expanduser()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Der angegebene Ordnerpfad existiert nicht oder ist kein Ordner.",
        )

    folder_resolved = folder.resolve()
    projects_root = PROJECTS_DIR.resolve()
    if folder_resolved == projects_root or projects_root in folder_resolved.parents or folder_resolved in projects_root.parents:
        raise HTTPException(
            status_code=400,
            detail="Bitte einen externen Projektordner waehlen, nicht den internen Projektspeicher.",
        )

    root_name = folder.name or "projektordner"
    collected: list[tuple[Path, str]] = []
    for item in sorted(folder.rglob("*")):
        if item.is_file():
            relative = item.relative_to(folder)
            collected.append((item, f"{root_name}/{relative.as_posix()}"))
    if not collected:
        raise HTTPException(status_code=400, detail="Der angegebene Ordner enthaelt keine importierbaren Dateien.")

    state = resolve_upload_project(project_id, root_name)
    try:
        # Quellpfade sind echte Dateien auf der Platte -> jede Datei wird genau
        # einmal nach 00_original/ kopiert (kein Temp-Zwischenschritt).
        import_uploaded_files(state["id"], collected)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Eine ZIP-Datei im Ordner konnte nicht gelesen werden.") from exc

    return RedirectResponse(f"/prototype/klassifizieren?project_id={state['id']}&saved=1#workflow", status_code=303)


@app.get("/prototype/{step_id}", response_class=HTMLResponse)
def prototype_step_page(request: Request, step_id: str) -> HTMLResponse:
    if not any(step["id"] == step_id for step in PROTOTYPE_STEPS):
        raise HTTPException(status_code=404, detail="Schritt nicht gefunden")
    return render_prototype(request, step_id)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(project_id: str) -> RedirectResponse:
    # Die alte project.html-Ansicht ist abgeloest; alles laeuft ueber den
    # 17-Schritte-Workflow. Alte Links bleiben ueber den Redirect gueltig.
    try:
        load_state(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden") from exc
    return RedirectResponse(f"/prototype/dateien?project_id={project_id}", status_code=303)


@app.get("/projects/{project_id}/download")
def download_route(project_id: str, path: str) -> FileResponse:
    file_path = resolve_project_file(project_id, path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return FileResponse(file_path, filename=file_path.name)


@app.get("/steps", response_class=HTMLResponse)
def steps_page(request: Request, step: str | None = None) -> HTMLResponse:
    steps = load_steps()
    if not steps:
        raise HTTPException(status_code=500, detail=f"Keine Workflow-Dateien in {WORKFLOW_DIR}")
    selected = load_step(step) if step else steps[0]
    return templates.TemplateResponse(
        "steps.html",
        {
            "request": request,
            "steps": steps,
            "selected": selected,
        },
    )


@app.post("/steps/{step_id}")
def save_step_route(
    step_id: str,
    instruction: Annotated[str, Form()],
    review_prompt: Annotated[str, Form()],
) -> RedirectResponse:
    save_step(step_id, instruction, review_prompt)
    return RedirectResponse(f"/steps?step={step_id}", status_code=303)
