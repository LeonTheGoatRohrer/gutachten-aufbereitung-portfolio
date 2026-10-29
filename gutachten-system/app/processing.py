from __future__ import annotations

import csv
import re
import shutil
import subprocess
import zipfile
from io import StringIO
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter

from .storage import append_log, load_state, now_iso, project_dir, resolve_project_file, save_state, slugify


PROBE_RE = re.compile(r"\bP(?:robe)?\s*0*(\d{1,3})\b", re.IGNORECASE)


def normalize_probe(value: Any) -> str:
    text = str(value or "").strip()
    match = PROBE_RE.search(text)
    if match:
        return f"P{int(match.group(1)):02d}"
    if isinstance(value, (int, float)) and int(value) == value:
        return f"P{int(value):02d}"
    if text.isdigit():
        return f"P{int(text):02d}"
    return text.upper()


def value_display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text.replace(".", ",")
    if isinstance(value, int):
        return str(value)
    text = str(value).strip().replace("\xa0", " ")
    if re.match(r"^[<>]\s*\d+[.]\d+$", text):
        sign = text[0]
        number = text[1:].strip().replace(".", ",")
        return f"{sign} {number}"
    return text


def chloride_numeric(display: str) -> float | None:
    text = str(display or "").strip()
    match = re.search(r"([0-9]+(?:[,.][0-9]+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _cell_text(value: Any) -> str:
    return str(value or "").strip()


def _sample_count(row: tuple[Any, ...]) -> int:
    return sum(1 for cell in row if PROBE_RE.search(_cell_text(cell)))


def _extract_horizontal(ws: Any) -> list[dict[str, Any]]:
    rows = list(ws.iter_rows(values_only=True))
    samples: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        row_text = " ".join(_cell_text(cell).lower() for cell in row[:5])
        if "chlorid" not in row_text:
            continue

        sample_row_index = None
        best_count = 0
        for candidate_index in range(max(0, row_index - 4), row_index):
            count = _sample_count(rows[candidate_index])
            if count > best_count:
                best_count = count
                sample_row_index = candidate_index
        if sample_row_index is None or best_count == 0:
            continue

        unit = value_display(row[1] if len(row) > 1 else "")
        sample_row = rows[sample_row_index]
        for col_index, sample_cell in enumerate(sample_row):
            probe = normalize_probe(sample_cell)
            if not probe.startswith("P"):
                continue
            value = row[col_index] if col_index < len(row) else None
            display = value_display(value)
            if not display:
                continue
            samples.append(
                {
                    "probe": probe,
                    "sample_label": value_display(sample_cell),
                    "chloride_display": display,
                    "chloride_numeric": chloride_numeric(display),
                    "unit": unit or "Masse-%",
                    "source": f"{ws.title}!{get_column_letter(col_index + 1)}{row_index + 1}",
                    "confidence": "sicher",
                }
            )
    return samples


def _extract_vertical(ws: Any) -> list[dict[str, Any]]:
    rows = list(ws.iter_rows(values_only=True))
    samples: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        lowered = [_cell_text(cell).lower() for cell in row]
        joined = " ".join(lowered)
        if "position" not in joined or ("proben" not in joined and "probe" not in joined):
            continue

        probe_col = 0
        chloride_col = None
        unit = "Masse-%"
        for col, text in enumerate(lowered):
            if "cl" in text or "chlorid" in text:
                chloride_col = col
                if idx + 1 < len(rows) and rows[idx + 1][col]:
                    unit = value_display(rows[idx + 1][col])
                break
        if chloride_col is None:
            continue

        for data_idx in range(idx + 2, len(rows)):
            data = rows[data_idx]
            if not any(_cell_text(cell) for cell in data[:6]):
                continue
            probe = normalize_probe(data[probe_col] if probe_col < len(data) else "")
            display = value_display(data[chloride_col] if chloride_col < len(data) else "")
            if not probe.startswith("P") or not display:
                continue
            samples.append(
                {
                    "probe": probe,
                    "sample_label": probe,
                    "chloride_display": display,
                    "chloride_numeric": chloride_numeric(display),
                    "unit": unit or "Masse-%",
                    "source": f"{ws.title}!{get_column_letter(chloride_col + 1)}{data_idx + 1}",
                    "confidence": "sicher",
                }
            )
    return samples


def extract_lab_values(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    workbook = load_workbook(path, data_only=True, read_only=True)
    samples: list[dict[str, Any]] = []
    for ws in workbook.worksheets:
        samples.extend(_extract_horizontal(ws))
        samples.extend(_extract_vertical(ws))

    deduped: dict[str, dict[str, Any]] = {}
    for sample in samples:
        probe = sample["probe"]
        if probe in deduped:
            warnings.append(f"Doppelter Laborwert fuer {probe}: {sample['source']} wurde ignoriert.")
            continue
        deduped[probe] = sample

    ordered = sorted(deduped.values(), key=lambda item: (item["probe"], item["source"]))
    if not ordered:
        warnings.append("Keine Laborwerte erkannt. Bitte Excel-Datei oder Schritt 02 pruefen.")
    return ordered, warnings


def _read_csv_rows(path: Path, max_rows: int = 40, max_cols: int = 20) -> list[list[Any]]:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = path.read_text(errors="replace")

    sample = text[:2000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";\t,")
    except csv.Error:
        dialect = csv.excel
    rows: list[list[Any]] = []
    for row in csv.reader(StringIO(text), dialect):
        rows.append(row[:max_cols])
        if len(rows) >= max_rows:
            break
    return rows


def _sheet_names(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return ["CSV"]
    if suffix in {".xlsx", ".xlsm"}:
        workbook = load_workbook(path, data_only=True, read_only=True)
        try:
            return workbook.sheetnames
        finally:
            workbook.close()
    return []


def _preview_rows(path: Path, sheet_name: str, max_rows: int = 40, max_cols: int = 20) -> list[list[Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv_rows(path, max_rows=max_rows, max_cols=max_cols)
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        worksheet = workbook[sheet_name] if sheet_name in workbook.sheetnames else workbook.worksheets[0]
        rows: list[list[Any]] = []
        for row in worksheet.iter_rows(values_only=True, max_row=max_rows, max_col=max_cols):
            rows.append(list(row))
        return rows
    finally:
        workbook.close()


def load_lab_preview(
    project_id: str,
    lab_relative_path: str,
    sheet_name: str | None = None,
    max_rows: int = 40,
    max_cols: int = 20,
) -> dict[str, Any]:
    source = resolve_project_file(project_id, lab_relative_path)
    suffix = source.suffix.lower()
    warnings: list[str] = []
    if suffix == ".xls":
        return {
            "supported": False,
            "source": lab_relative_path,
            "sheets": [],
            "selected_sheet": "",
            "headers": [],
            "rows": [],
            "warnings": [
                ".xls wird im Prototyp noch nicht direkt gelesen. Bitte als .xlsx oder .csv speichern."
            ],
        }
    if suffix not in {".xlsx", ".xlsm", ".csv"}:
        return {
            "supported": False,
            "source": lab_relative_path,
            "sheets": [],
            "selected_sheet": "",
            "headers": [],
            "rows": [],
            "warnings": ["Dieser Dateityp wird fuer die Laborvorschau noch nicht unterstuetzt."],
        }

    sheets = _sheet_names(source)
    selected_sheet = sheet_name if sheet_name in sheets else (sheets[0] if sheets else "")
    raw_rows = _preview_rows(source, selected_sheet, max_rows=max_rows, max_cols=max_cols) if selected_sheet else []
    used_cols = max((len(row) for row in raw_rows), default=0)
    headers = [get_column_letter(index + 1) for index in range(used_cols)]
    rows = [
        {
            "number": row_index,
            "cells": [value_display(value) for value in row] + [""] * (used_cols - len(row)),
        }
        for row_index, row in enumerate(raw_rows, start=1)
    ]
    if not rows:
        warnings.append("Keine Vorschauzeilen gefunden.")

    return {
        "supported": True,
        "source": lab_relative_path,
        "sheets": sheets,
        "selected_sheet": selected_sheet,
        "headers": headers,
        "rows": rows,
        "warnings": warnings,
        "limit_rows": max_rows,
        "limit_cols": max_cols,
    }


def _manual_cell_matrix(path: Path, sheet_name: str) -> list[list[Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv_rows(path, max_rows=1000, max_cols=200)
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        worksheet = workbook[sheet_name] if sheet_name in workbook.sheetnames else workbook.worksheets[0]
        return [list(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def extract_lab_values_manual(
    project_id: str,
    lab_relative_path: str,
    sheet_name: str,
    sample_row: int,
    value_row: int,
    unit: str = "",
    first_col: str = "",
    last_col: str = "",
) -> dict[str, Any]:
    source = resolve_project_file(project_id, lab_relative_path)
    rows = _manual_cell_matrix(source, sheet_name)
    if sample_row < 1 or value_row < 1 or sample_row > len(rows) or value_row > len(rows):
        raise ValueError("Probenzeile oder Wertzeile liegt ausserhalb der Vorschau.")

    sample_values = rows[sample_row - 1]
    chloride_values = rows[value_row - 1]
    max_cols = max(len(sample_values), len(chloride_values))
    start_col = 1
    end_col = max_cols
    if first_col.strip():
        start_col = column_index_from_string(first_col.strip().upper())
    if last_col.strip():
        end_col = column_index_from_string(last_col.strip().upper())
    start_col = max(start_col, 1)
    end_col = min(end_col, max_cols)
    if start_col > end_col:
        raise ValueError("Die erste Spalte liegt nach der letzten Spalte.")

    samples: list[dict[str, Any]] = []
    warnings: list[str] = []
    for col_index in range(start_col - 1, end_col):
        sample_cell = sample_values[col_index] if col_index < len(sample_values) else ""
        probe = normalize_probe(sample_cell)
        if not probe.startswith("P"):
            continue
        value = chloride_values[col_index] if col_index < len(chloride_values) else ""
        display = value_display(value)
        if not display:
            warnings.append(f"Kein Chloridwert fuer {probe} in Spalte {get_column_letter(col_index + 1)}.")
            continue
        samples.append(
            {
                "probe": probe,
                "sample_label": value_display(sample_cell),
                "chloride_display": display,
                "chloride_numeric": chloride_numeric(display),
                "unit": unit.strip() or "Masse-%",
                "source": f"{sheet_name}!{get_column_letter(col_index + 1)}{value_row}",
                "confidence": "manuell bestaetigt",
            }
        )

    if not samples:
        warnings.append("Keine Proben in der gewaehlten Probenzeile erkannt.")

    state = load_state(project_id)
    state.setdefault("selected_files", {})["lab_file"] = lab_relative_path
    state["lab_values"] = samples
    state["lab_manual_selection"] = {
        "sheet_name": sheet_name,
        "sample_row": sample_row,
        "value_row": value_row,
        "unit": unit.strip() or "Masse-%",
        "first_col": first_col.strip().upper(),
        "last_col": last_col.strip().upper(),
    }
    state.setdefault("outputs", {}).pop("clean_lab_values", None)
    state.pop("lab_clean_table_saved_at", None)
    state["lab_table_accepted"] = False
    state.pop("lab_table_accepted_at", None)
    state["lab_warnings"] = warnings
    state["status"] = "Laborwerte vorbereitet"
    append_log(state, f"Laborwerte vorbereitet: {len(samples)} Proben fuer Zwischentabelle erkannt.")
    for warning in warnings:
        append_log(state, f"WARNUNG Labor manuell: {warning}")
    save_state(project_id, state)
    return state


def autosize(ws: Any) -> None:
    for column_cells in ws.columns:
        length = max(len(str(cell.value or "")) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(length + 2, 12), 42)


def write_lab_workbook(path: Path, samples: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Laborwerte"
    headers = ["Probe", "Chloridwert", "Numerisch", "Einheit", "Quelle", "Sicherheit"]
    ws.append(headers)
    for sample in samples:
        ws.append(
            [
                sample.get("probe", ""),
                sample.get("chloride_display", ""),
                sample.get("chloride_numeric", ""),
                sample.get("unit", ""),
                sample.get("source", ""),
                sample.get("confidence", ""),
            ]
        )
    ws.auto_filter.ref = f"A1:F{max(ws.max_row, 1)}"
    ws.sheet_view.showGridLines = False
    style_header(ws)
    thin = Side(style="thin", color="D9E1E8")
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
        fill = PatternFill("solid", fgColor="F8FAFB" if row[0].row % 2 == 0 else "FFFFFF")
        for cell in row:
            cell.fill = fill
            cell.border = Border(bottom=thin)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        row[0].font = Font(bold=True, color="172026")
        row[2].number_format = "0.00"
    autosize(ws)
    wb.save(path)


def accept_lab_table(project_id: str) -> dict[str, Any]:
    """Markiert die geprueft Zwischentabelle als akzeptiert und gibt die
    formatierte Excel-Vorschau frei. Es wird noch keine Datei geschrieben."""
    state = load_state(project_id)
    samples = state.get("lab_values", [])
    if not samples:
        raise ValueError("Es gibt noch keine bereinigte Zwischentabelle zum Akzeptieren.")
    state["lab_table_accepted"] = True
    state["lab_table_accepted_at"] = now_iso()
    state["status"] = "Zwischentabelle akzeptiert"
    append_log(
        state,
        f"Zwischentabelle akzeptiert: {len(samples)} Werte fuer die formatierte Excel-Vorschau freigegeben.",
    )
    save_state(project_id, state)
    return state


def clean_lab_output_name(state: dict[str, Any], project_id: str) -> str:
    """Erzeugt einen sprechenden Dateinamen fuer die bereinigte Labor-Excel."""
    base = state.get("project", {}).get("name") or project_id
    return f"Laborwerte_bereinigt_{slugify(base)}.xlsx"


def save_clean_lab_table(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    samples = state.get("lab_values", [])
    if not samples:
        raise ValueError("Es gibt noch keine bereinigte Zwischentabelle zum Speichern.")
    if not state.get("lab_table_accepted"):
        raise ValueError("Bitte die Zwischentabelle zuerst akzeptieren, bevor sie gespeichert wird.")
    filename = clean_lab_output_name(state, project_id)
    output = project_dir(project_id) / "Output" / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    write_lab_workbook(output, samples)
    relative = str(output.relative_to(project_dir(project_id)).as_posix())
    state.setdefault("outputs", {})["clean_lab_values"] = relative
    state["lab_clean_table_saved_at"] = now_iso()
    state["status"] = "Bereinigte Labor-Excel in Output gespeichert"
    append_log(state, f"Bereinigte Labor-Excel in Output gespeichert: {relative} ({len(samples)} Werte).")
    save_state(project_id, state)
    return state


def clean_lab_for_project(project_id: str, lab_relative_path: str) -> dict[str, Any]:
    source = resolve_project_file(project_id, lab_relative_path)
    samples, warnings = extract_lab_values(source)
    output = project_dir(project_id) / "02_processed" / "clean_lab_values.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_lab_workbook(output, samples)

    state = load_state(project_id)
    state["selected_files"]["lab_file"] = lab_relative_path
    state["lab_values"] = samples
    state["outputs"]["clean_lab_values"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["lab_warnings"] = warnings
    state["status"] = "Laborwerte bereinigt"
    append_log(state, f"Laborwerte bereinigt: {len(samples)} Proben erkannt.")
    for warning in warnings:
        append_log(state, f"WARNUNG Labor: {warning}")
    save_state(project_id, state)
    return state


def parse_field_measurements(text: str, known_probes: list[str]) -> list[dict[str, Any]]:
    clean = text.strip()
    if not clean and known_probes:
        return [
            {
                "probe": probe,
                "position": "",
                "drill_depth_mm": "",
                "height_cm": "",
                "carbonation": "",
                "remark": "aus Laborliste vorbereitet",
                "status": "Pruefung erforderlich",
            }
            for probe in known_probes
        ]

    if not clean:
        return []

    sample = clean[:1000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t;,")
    except csv.Error:
        dialect = csv.excel_tab
    reader = csv.reader(StringIO(clean), dialect)
    rows = [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return []

    header = [cell.lower() for cell in rows[0]]
    has_header = any("probe" in cell or "proben" in cell or "nr" == cell for cell in header)
    data_rows = rows[1:] if has_header else rows

    def index_for(tokens: list[str], fallback: int) -> int:
        if has_header:
            for idx, cell in enumerate(header):
                if any(token in cell for token in tokens):
                    return idx
        return fallback

    probe_idx = index_for(["probe", "proben", "nr"], 0)
    position_idx = index_for(["position", "situierung"], 1)
    depth_idx = index_for(["bohr", "tiefe"], 2)
    height_idx = index_for(["hoehe", "höhe"], 3)
    carbonation_idx = index_for(["karbon"], 4)
    remark_idx = index_for(["bemerk", "status", "kommentar"], 5)

    measurements: list[dict[str, Any]] = []
    for row in data_rows:
        def get(idx: int) -> str:
            return row[idx].strip() if idx < len(row) else ""

        probe = normalize_probe(get(probe_idx))
        if not probe:
            continue
        status = "ok"
        remark = get(remark_idx)
        if "?" in " ".join(row) or "unsicher" in remark.lower():
            status = "Pruefung erforderlich"
        measurements.append(
            {
                "probe": probe,
                "position": get(position_idx),
                "drill_depth_mm": get(depth_idx),
                "height_cm": get(height_idx),
                "carbonation": get(carbonation_idx),
                "remark": remark,
                "status": status,
            }
        )
    return measurements


def write_field_workbook(path: Path, measurements: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Vor-Ort-Werte"
    headers = ["Probe", "Position", "Bohrtiefe [mm]", "Hoehe [cm]", "Karbonatisierung", "Bemerkung", "Status"]
    ws.append(headers)
    for item in measurements:
        ws.append(
            [
                item.get("probe", ""),
                item.get("position", ""),
                item.get("drill_depth_mm", ""),
                item.get("height_cm", ""),
                item.get("carbonation", ""),
                item.get("remark", ""),
                item.get("status", ""),
            ]
        )
    style_header(ws)
    autosize(ws)
    wb.save(path)


def save_field_measurements(project_id: str, text: str) -> dict[str, Any]:
    state = load_state(project_id)
    known_probes = [item["probe"] for item in state.get("lab_values", [])]
    measurements = parse_field_measurements(text, known_probes)
    output = project_dir(project_id) / "02_processed" / "field_measurements.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_field_workbook(output, measurements)

    state["field_measurements"] = measurements
    state["field_text"] = text
    state.pop("field_measurements_unavailable", None)
    state.pop("field_measurements_mock", None)
    state["outputs"]["field_measurements"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Vor-Ort-Werte gespeichert"
    append_log(state, f"Vor-Ort-Werte gespeichert: {len(measurements)} Zeilen.")
    save_state(project_id, state)
    return state


def create_mock_field_measurements(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    probes = [item["probe"] for item in state.get("lab_values", [])]
    if not probes:
        probes = [f"P{index:02d}" for index in range(1, 23)]
    measurements: list[dict[str, Any]] = []
    for index, probe in enumerate(probes, start=1):
        depth = 20 if index % 2 else 40
        height = "10"
        location = (index + 1) // 2
        measurements.append(
            {
                "probe": probe,
                "position": f"MOCK Beprobungsstelle {location:02d}",
                "drill_depth_mm": str(depth),
                "height_cm": height,
                "carbonation": "MOCK nicht fachlich bewertet",
                "remark": "MOCKDATEN - nur fuer Prototyp-Durchlauf ersetzen",
                "status": "Mockdaten - ersetzen",
            }
        )

    output = project_dir(project_id) / "02_processed" / "field_measurements.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_field_workbook(output, measurements)

    state["field_measurements"] = measurements
    state["field_text"] = ""
    state.pop("field_measurements_unavailable", None)
    state["field_measurements_mock"] = {
        "reason": "Mockdaten fuer Prototyp-Durchlauf. Nicht fuer fachliche Verwendung.",
        "saved_at": now_iso(),
    }
    state["outputs"]["field_measurements"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Mock-Vor-Ort-Werte erzeugt"
    append_log(state, f"Mock-Vor-Ort-Werte erzeugt: {len(measurements)} Zeilen.")
    save_state(project_id, state)
    return state


def mark_field_measurements_unavailable(project_id: str, reason: str = "") -> dict[str, Any]:
    state = load_state(project_id)
    output = project_dir(project_id) / "02_processed" / "field_measurements.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_field_workbook(output, [])

    note = reason.strip() or "Vom Auftraggeber wurden keine Vor-Ort-Werte geliefert."
    state["field_measurements"] = []
    state["field_text"] = ""
    state["field_measurements_unavailable"] = {"reason": note, "saved_at": now_iso()}
    state.pop("field_measurements_mock", None)
    state["outputs"]["field_measurements"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Vor-Ort-Werte nicht geliefert"
    append_log(state, f"Vor-Ort-Werte uebersprungen: {note}")
    save_state(project_id, state)
    return state


def _group_key_for_position(position: str, probe: str) -> tuple[str, str]:
    clean_position = " ".join(str(position or "").split())
    if clean_position:
        return ("position", clean_position.lower())
    return ("probe", probe)


def _group_status(items: list[dict[str, Any]], field_mock: bool) -> str:
    status_parts: list[str] = []
    if any(not item.get("position") for item in items):
        status_parts.append("Position fehlt")
    if field_mock or any("mock" in str(item.get("status", "")).lower() for item in items):
        status_parts.append("Mockdaten ersetzen")
    if any(str(item.get("status", "")).lower() not in {"", "ok"} for item in items):
        status_parts.append("Pruefung erforderlich")
    return "; ".join(dict.fromkeys(status_parts)) if status_parts else "Vorschlag ok"


def write_sample_groups_workbook(path: Path, groups: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Beprobungsstellen"
    ws.append(["Beprobungsstelle", "Position", "Proben", "Bohrtiefen [mm]", "Hoehen [cm]", "Karbonatisierung", "Status"])
    for group in groups:
        ws.append(
            [
                group.get("group_id", ""),
                group.get("position", ""),
                group.get("probes", ""),
                group.get("drill_depths", ""),
                group.get("heights", ""),
                group.get("carbonation", ""),
                group.get("status", ""),
            ]
        )
    _apply_table_style(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def generate_sample_groups(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    measurements = state.get("field_measurements", [])
    if not measurements:
        if state.get("field_measurements_unavailable"):
            raise ValueError("Keine Vor-Ort-Daten vorhanden. Schritt 7 kann erst nach CSV/TSV-Import oder Mockdaten Gruppierungen vorschlagen.")
        raise ValueError("Bitte zuerst Schritt 6 mit Vor-Ort-Daten, CSV/TSV oder Mockdaten ausfuehren.")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in measurements:
        probe = item.get("probe", "")
        grouped.setdefault(_group_key_for_position(item.get("position", ""), probe), []).append(item)

    def probe_number(probe: str) -> int:
        match = re.search(r"\d+", str(probe or ""))
        return int(match.group(0)) if match else 9999

    groups: list[dict[str, Any]] = []
    for index, (_, items) in enumerate(
        sorted(grouped.items(), key=lambda pair: (pair[0][0] != "position", pair[0][1])),
        start=1,
    ):
        ordered_items = sorted(items, key=lambda item: probe_number(item.get("probe", "")))
        probes = [item.get("probe", "") for item in ordered_items if item.get("probe")]
        position = next((item.get("position", "") for item in ordered_items if item.get("position")), "")
        drill_depths = [str(item.get("drill_depth_mm", "")).strip() for item in ordered_items if str(item.get("drill_depth_mm", "")).strip()]
        heights = [str(item.get("height_cm", "")).strip() for item in ordered_items if str(item.get("height_cm", "")).strip()]
        carbonations = [
            str(item.get("carbonation", "")).strip()
            for item in ordered_items
            if str(item.get("carbonation", "")).strip()
        ]
        groups.append(
            {
                "group_id": f"BS{index:02d}",
                "position": position,
                "probes": ", ".join(probes),
                "drill_depths": ", ".join(dict.fromkeys(drill_depths)),
                "heights": ", ".join(dict.fromkeys(heights)),
                "carbonation": "; ".join(dict.fromkeys(carbonations)),
                "status": _group_status(ordered_items, bool(state.get("field_measurements_mock"))),
                "sample_count": len(ordered_items),
            }
        )

    output = project_dir(project_id) / "04_tables" / "sample_groups.xlsx"
    write_sample_groups_workbook(output, groups)

    state["sample_groups"] = groups
    state.setdefault("outputs", {})["sample_groups"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Proben gruppiert"
    append_log(state, f"Proben gruppiert: {len(groups)} Beprobungsstellen vorgeschlagen.")
    save_state(project_id, state)
    return state


def _group_by_probe(sample_groups: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for group in sample_groups:
        group_id = group.get("group_id", "")
        probes = [normalize_probe(part.strip()) for part in str(group.get("probes", "")).split(",")]
        for probe in probes:
            if probe:
                mapping[probe] = group_id
    return mapping


def _merge_status(
    lab: dict[str, Any],
    field: dict[str, Any],
    field_unavailable: bool,
    field_mock: bool,
) -> str:
    status_parts: list[str] = []
    if not lab.get("chloride_display"):
        status_parts.append("Laborwert fehlt")
    if field_unavailable and not field:
        status_parts.append("Vor-Ort-Daten nicht geliefert")
    elif not field:
        status_parts.append("Vor-Ort-Werte fehlen")
    else:
        if not field.get("position"):
            status_parts.append("Position fehlt")
        if not field.get("drill_depth_mm"):
            status_parts.append("Bohrtiefe fehlt")
        if not field.get("height_cm"):
            status_parts.append("Hoehe fehlt")
        if not field.get("carbonation"):
            status_parts.append("Karbonatisierung offen")
        if field.get("status") == "Pruefung erforderlich":
            status_parts.append("Vor-Ort-Wert unsicher")
        if field_mock or "mock" in str(field.get("status", "")).lower():
            status_parts.append("Mockdaten ersetzen")
    return "; ".join(status_parts) if status_parts else "Verbunden"


def write_lab_field_merge_workbook(path: Path, rows: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Labor Vor-Ort"
    ws.append(
        [
            "Probe",
            "Beprobungsstelle",
            "Position",
            "Bohrtiefe [mm]",
            "Hoehe [cm]",
            "Karbonatisierung",
            "%Cl(Zement) Masse-%",
            "Einheit",
            "Laborquelle",
            "Status",
        ]
    )
    for row in rows:
        ws.append(
            [
                row.get("probe", ""),
                row.get("group_id", ""),
                row.get("position", ""),
                row.get("drill_depth_mm", ""),
                row.get("height_cm", ""),
                row.get("carbonation", ""),
                row.get("chloride_display", ""),
                row.get("unit", ""),
                row.get("source", ""),
                row.get("status", ""),
            ]
        )
    _apply_table_style(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def generate_lab_field_merge(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    lab_by_probe = {item["probe"]: item for item in state.get("lab_values", [])}
    field_by_probe = {item["probe"]: item for item in state.get("field_measurements", [])}
    field_unavailable = bool(state.get("field_measurements_unavailable")) and not field_by_probe
    field_mock = bool(state.get("field_measurements_mock"))
    group_by_probe = _group_by_probe(state.get("sample_groups", []))
    probes = sorted(set(lab_by_probe) | set(field_by_probe))
    if not probes:
        raise ValueError("Keine Labor- oder Vor-Ort-Proben vorhanden. Bitte zuerst Schritt 4 und Schritt 6 ausfuehren.")

    rows: list[dict[str, Any]] = []
    for probe in probes:
        lab = lab_by_probe.get(probe, {})
        field = field_by_probe.get(probe, {})
        rows.append(
            {
                "probe": probe,
                "group_id": group_by_probe.get(probe, ""),
                "position": field.get("position", ""),
                "drill_depth_mm": field.get("drill_depth_mm", ""),
                "height_cm": field.get("height_cm", ""),
                "carbonation": field.get("carbonation", ""),
                "chloride_display": lab.get("chloride_display", ""),
                "chloride_numeric": lab.get("chloride_numeric"),
                "unit": lab.get("unit", "Masse-%") if lab else "",
                "source": lab.get("source", ""),
                "status": _merge_status(lab, field, field_unavailable, field_mock),
            }
        )

    output = project_dir(project_id) / "04_tables" / "Labor_VorOrt_Verbindung.xlsx"
    write_lab_field_merge_workbook(output, rows)

    state["lab_field_merge"] = rows
    state.setdefault("outputs", {})["lab_field_merge"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Labor und Vor-Ort verbunden"
    append_log(state, f"Labor und Vor-Ort verbunden: {len(rows)} Proben abgeglichen.")
    save_state(project_id, state)
    return state


def is_carbonation_critical(value: str) -> bool:
    text = str(value or "").lower()
    return any(token in text for token in ["bewehrung", "kritisch", "bis bewehrung", "an bewehrung"])


def rating_for(
    chloride: float | None,
    carbonation: str,
    field_context_available: bool = True,
) -> tuple[str, str, str]:
    if chloride is None:
        return "Pruefung erforderlich", "pruefen", "Kein numerischer Chloridwert erkannt."
    if not field_context_available:
        if chloride > 1.0:
            return (
                "Laborwert auffaellig",
                "pruefen",
                "Chloridwert ueber 1,0 %, aber Vor-Ort-Daten fuer Gesamtbewertung fehlen.",
            )
        return (
            "Laborwert vorhanden",
            "pruefen",
            "Vor-Ort-Daten fuer fachliche Gesamtbewertung fehlen.",
        )
    if chloride > 1.0:
        return "stark kritisch", "rot", "Chloridwert ueber 1,0 %."
    if 0.2 <= chloride <= 1.0:
        return "Pruefung erforderlich", "pruefen", "0,2 bis 1,0 %, fachlich pruefen. Orange wird nicht automatisch gesetzt."
    return "normal", "normal", "Chloridwert unter 0,2 %."


def generate_master(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    lab_by_probe = {item["probe"]: item for item in state.get("lab_values", [])}
    field_by_probe = {item["probe"]: item for item in state.get("field_measurements", [])}
    field_unavailable = bool(state.get("field_measurements_unavailable")) and not field_by_probe
    field_mock = bool(state.get("field_measurements_mock"))
    probes = sorted(set(lab_by_probe) | set(field_by_probe))

    master: list[dict[str, Any]] = []
    for probe in probes:
        lab = lab_by_probe.get(probe, {})
        field = field_by_probe.get(probe, {})
        carbonation = field.get("carbonation", "")
        has_field_context = bool(field) or not field_unavailable
        rating, color, reason = rating_for(lab.get("chloride_numeric"), carbonation, has_field_context)
        status_parts = []
        if field_unavailable and not field:
            status_parts.append("Vor-Ort-Daten nicht geliefert")
        else:
            if not field.get("position"):
                status_parts.append("Position fehlt")
            if not field.get("drill_depth_mm"):
                status_parts.append("Bohrtiefe fehlt")
            if not field.get("height_cm"):
                status_parts.append("Hoehe fehlt")
        if not lab.get("chloride_display"):
            status_parts.append("Chloridwert fehlt")
        if not carbonation and not field_unavailable:
            status_parts.append("Karbonatisierung offen")
        if field.get("status") == "Pruefung erforderlich":
            status_parts.append("Vor-Ort-Wert unsicher")
        if field_mock or "mock" in str(field.get("status", "")).lower():
            status_parts.append("Mockdaten ersetzen")

        master.append(
            {
                "probe": probe,
                "position": field.get("position", ""),
                "drill_depth_mm": field.get("drill_depth_mm", ""),
                "height_cm": field.get("height_cm", ""),
                "chloride_display": lab.get("chloride_display", ""),
                "chloride_numeric": lab.get("chloride_numeric"),
                "unit": lab.get("unit", "Masse-%"),
                "carbonation": carbonation,
                "rating": rating,
                "color": color,
                "rating_reason": reason,
                "status": "; ".join(status_parts) if status_parts else "ok",
            }
        )

    output = project_dir(project_id) / "04_tables" / "Master_Probenliste.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_master_workbook(output, master)

    state["master_samples"] = master
    state["outputs"]["master_samples"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Master-Probenliste erzeugt"
    append_log(state, f"Master-Probenliste erzeugt: {len(master)} Proben.")
    save_state(project_id, state)
    return state


def write_marking_proposals_workbook(path: Path, rows: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Markierungsvorschlaege"
    ws.append(["Probe", "Chlorid", "Numerischer Wert", "Farbe", "Vorschlag", "Begruendung", "Status"])
    fills = {
        "rot": PatternFill("solid", fgColor="FCA5A5"),
        "orange": PatternFill("solid", fgColor="FDBA74"),
        "normal": PatternFill("solid", fgColor="FFFFFF"),
        "pruefen": PatternFill("solid", fgColor="FEF3C7"),
    }
    for row in rows:
        ws.append(
            [
                row.get("probe", ""),
                row.get("chloride_display", ""),
                row.get("chloride_numeric", ""),
                row.get("color", ""),
                row.get("proposal", ""),
                row.get("reason", ""),
                row.get("status", ""),
            ]
        )
        fill = fills.get(row.get("color", "normal"), fills["normal"])
        for cell in ws[ws.max_row]:
            cell.fill = fill
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    _apply_table_style(ws, preserve_fills=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def generate_marking_proposals(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    master = state.get("master_samples", [])
    if not master:
        raise ValueError("Bitte zuerst Schritt 9 mit der Master-Probenliste ausfuehren.")

    proposals: list[dict[str, Any]] = []
    for item in master:
        color = item.get("color", "")
        proposal = "Keine automatische Markierung"
        if color == "rot":
            proposal = "Rot vorschlagen"
        elif color == "pruefen":
            proposal = "Pruefung durch SV"
        proposals.append(
            {
                "probe": item.get("probe", ""),
                "chloride_display": item.get("chloride_display", ""),
                "chloride_numeric": item.get("chloride_numeric"),
                "color": color,
                "proposal": proposal,
                "reason": item.get("rating_reason", ""),
                "status": item.get("status", ""),
            }
        )

    output = project_dir(project_id) / "04_tables" / "Markierungsvorschlaege.xlsx"
    write_marking_proposals_workbook(output, proposals)
    state["marking_proposals"] = proposals
    state.setdefault("outputs", {})["marking_proposals"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Markierungsvorschlaege erzeugt"
    append_log(state, f"Markierungsvorschlaege erzeugt: {len(proposals)} Proben.")
    save_state(project_id, state)
    return state


def write_image_inventory_workbook(path: Path, rows: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Bildinventar"
    ws.append(["Bild-ID", "Dateiname", "Pfad", "Datum", "Groesse [KB]", "Verwenden", "Status"])
    for row in rows:
        ws.append(
            [
                row.get("image_id", ""),
                row.get("name", ""),
                row.get("path", ""),
                row.get("modified", ""),
                row.get("size_kb", ""),
                "ja" if row.get("use_in_report") else "nein",
                row.get("status", ""),
            ]
        )
    _apply_table_style(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def generate_image_inventory(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    selected_ids = set(state.get("selected_image_ids", []))
    images = [
        item
        for item in state.get("file_inventory", [])
        if item.get("category") == "Bild" or item.get("extension") in {".jpg", ".jpeg", ".png"}
    ]
    images = sorted(images, key=lambda item: (item.get("modified", ""), item.get("name", "")))
    inventory: list[dict[str, Any]] = []
    for index, item in enumerate(images, start=1):
        inventory.append(
            {
                "image_id": f"IMG{index:03d}",
                "name": item.get("name", ""),
                "path": item.get("path", ""),
                "modified": item.get("modified", ""),
                "size_kb": round((item.get("size") or 0) / 1024, 1),
                "use_in_report": f"IMG{index:03d}" in selected_ids,
                "status": "ausgewaehlt" if f"IMG{index:03d}" in selected_ids else "zur Auswahl",
            }
        )

    output = project_dir(project_id) / "04_tables" / "Bildinventar.xlsx"
    write_image_inventory_workbook(output, inventory)
    state["image_inventory"] = inventory
    state.setdefault("outputs", {})["image_inventory"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Bildinventar erzeugt"
    append_log(state, f"Bildinventar erzeugt: {len(inventory)} Bilder.")
    save_state(project_id, state)
    return state


def save_image_selection(project_id: str, selected_image_ids: list[str]) -> dict[str, Any]:
    state = load_state(project_id)
    inventory = state.get("image_inventory")
    if inventory is None:
        state = generate_image_inventory(project_id)
        inventory = state.get("image_inventory", [])

    valid_ids = {item.get("image_id", "") for item in inventory}
    selected = [image_id for image_id in selected_image_ids if image_id in valid_ids]
    selected_set = set(selected)
    for item in inventory:
        item["use_in_report"] = item.get("image_id") in selected_set
        item["status"] = "ausgewaehlt" if item["use_in_report"] else "nicht verwenden"

    output = project_dir(project_id) / "04_tables" / "Bildinventar.xlsx"
    write_image_inventory_workbook(output, inventory)
    state["image_inventory"] = inventory
    state["selected_image_ids"] = selected
    state.setdefault("outputs", {})["image_inventory"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state.pop("position_image_assignments", None)
    state.pop("image_captions", None)
    state["outputs"].pop("position_image_assignments", None)
    state["outputs"].pop("image_captions", None)
    state["status"] = "Bilder fuer Gutachten ausgewaehlt"
    append_log(state, f"Bilder fuer Gutachten ausgewaehlt: {len(selected)} von {len(inventory)} Bildern.")
    save_state(project_id, state)
    return state


def _match_image_for_group(group: dict[str, Any], images: list[dict[str, Any]]) -> dict[str, Any] | None:
    group_id = str(group.get("group_id", "")).lower()
    position = str(group.get("position", "")).lower()
    position_tokens = [token for token in re.split(r"[^a-z0-9]+", position) if len(token) >= 3]
    for image in images:
        haystack = f"{image.get('name', '')} {image.get('path', '')}".lower()
        if group_id and group_id in haystack:
            return image
        if position_tokens and all(token in haystack for token in position_tokens[:3]):
            return image
    return None


def write_position_images_workbook(path: Path, rows: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Positionsbilder"
    ws.append(["Beprobungsstelle", "Position", "Proben", "Bild-ID", "Bildpfad", "Status"])
    for row in rows:
        ws.append(
            [
                row.get("group_id", ""),
                row.get("position", ""),
                row.get("probes", ""),
                row.get("image_id", ""),
                row.get("image_path", ""),
                row.get("status", ""),
            ]
        )
    _apply_table_style(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def generate_position_image_assignments(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    groups = state.get("sample_groups", [])
    if not groups:
        raise ValueError("Bitte zuerst Schritt 7 mit der Gruppierung ausfuehren.")
    images = state.get("image_inventory")
    if images is None:
        state = generate_image_inventory(project_id)
        images = state.get("image_inventory", [])
    images = [image for image in images if image.get("use_in_report")]
    if not images:
        raise ValueError("Bitte zuerst in Schritt 11 Bilder fuer das Gutachten auswaehlen.")

    assignments: list[dict[str, Any]] = []
    used: set[str] = set()
    for group in groups:
        match = _match_image_for_group(group, images)
        image_id = match.get("image_id", "") if match else ""
        image_path = match.get("path", "") if match else ""
        if image_id:
            used.add(image_id)
        assignments.append(
            {
                "group_id": group.get("group_id", ""),
                "position": group.get("position", ""),
                "probes": group.get("probes", ""),
                "image_ids": [image_id] if image_id else [],
                "image_paths": [image_path] if image_path else [],
                "image_id": image_id,
                "image_path": image_path,
                "status": "Vorschlag pruefen" if match else "Bildzuordnung offen",
            }
        )

    unassigned_images = [
        {
            "group_id": "",
            "position": "",
            "probes": "",
            "image_id": image.get("image_id", ""),
            "image_path": image.get("path", ""),
            "status": "Nicht zugeordnet",
        }
        for image in images
        if image.get("image_id") not in used
    ]
    rows = assignments + unassigned_images
    output = project_dir(project_id) / "04_tables" / "Positionsbilder.xlsx"
    write_position_images_workbook(output, rows)
    state["position_image_assignments"] = rows
    state.setdefault("outputs", {})["position_image_assignments"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Positionsbilder vorbereitet"
    append_log(state, f"Positionsbilder vorbereitet: {len(assignments)} Beprobungsstellen, {len(unassigned_images)} nicht zugeordnete Bilder.")
    save_state(project_id, state)
    return state


def _assignment_image_ids(assignment: dict[str, Any]) -> list[str]:
    image_ids = assignment.get("image_ids")
    if isinstance(image_ids, list):
        return [str(image_id) for image_id in image_ids if str(image_id).strip()]
    image_id = str(assignment.get("image_id", "")).strip()
    return [part.strip() for part in image_id.split(",") if part.strip()]


def _prune_image_captions_to_assignments(state: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    existing_captions = state.get("image_captions")
    if not existing_captions:
        return
    valid_pairs = {
        (row.get("group_id", ""), image_id)
        for row in rows
        if row.get("group_id")
        for image_id in _assignment_image_ids(row)
    }
    kept = [
        caption
        for caption in existing_captions
        if (caption.get("group_id", ""), caption.get("image_id", "")) in valid_pairs
    ]
    if kept:
        state["image_captions"] = kept
        return
    state.pop("image_captions", None)
    state.get("outputs", {}).pop("image_captions", None)


def save_position_image_assignments(
    project_id: str,
    images_by_group: dict[str, list[str]],
    target_group_id: str | None = None,
) -> dict[str, Any]:
    state = load_state(project_id)
    groups = state.get("sample_groups", [])
    if not groups:
        raise ValueError("Bitte zuerst Schritt 7 mit der Gruppierung ausfuehren.")
    images = [image for image in state.get("image_inventory", []) if image.get("use_in_report")]
    if not images:
        raise ValueError("Bitte zuerst in Schritt 11 Bilder fuer das Gutachten auswaehlen.")

    image_by_id = {image.get("image_id", ""): image for image in images}
    if target_group_id:
        existing_by_group = {
            assignment.get("group_id", ""): _assignment_image_ids(assignment)
            for assignment in state.get("position_image_assignments", [])
            if assignment.get("group_id")
        }
        requested_by_group = {
            group.get("group_id", ""): existing_by_group.get(group.get("group_id", ""), [])
            for group in groups
        }
        requested_by_group[target_group_id] = images_by_group.get(target_group_id, [])
    else:
        requested_by_group = images_by_group

    assigned_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    for group in groups:
        group_id = group.get("group_id", "")
        image_ids = []
        for image_id in requested_by_group.get(group_id, []):
            clean_id = image_id.strip()
            if clean_id and clean_id in image_by_id and clean_id not in image_ids and clean_id not in assigned_ids:
                image_ids.append(clean_id)
        images_for_group = [image_by_id[image_id] for image_id in image_ids]
        assigned_ids.update(image_ids)
        image_paths = [image.get("path", "") for image in images_for_group if image.get("path")]
        rows.append(
            {
                "group_id": group_id,
                "position": group.get("position", ""),
                "probes": group.get("probes", ""),
                "image_ids": image_ids,
                "image_paths": image_paths,
                "image_id": ", ".join(image_ids),
                "image_path": "; ".join(image_paths),
                "status": "manuell zugeordnet" if image_ids else "Bildzuordnung offen",
            }
        )

    rows.extend(
        {
            "group_id": "",
            "position": "",
            "probes": "",
            "image_id": image.get("image_id", ""),
            "image_path": image.get("path", ""),
            "status": "Nicht zugeordnet",
        }
        for image in images
        if image.get("image_id") not in assigned_ids
    )

    output = project_dir(project_id) / "04_tables" / "Positionsbilder.xlsx"
    write_position_images_workbook(output, rows)
    state["position_image_assignments"] = rows
    state.setdefault("outputs", {})["position_image_assignments"] = str(output.relative_to(project_dir(project_id)).as_posix())
    if target_group_id:
        _prune_image_captions_to_assignments(state, rows)
    else:
        state.pop("image_captions", None)
        state["outputs"].pop("image_captions", None)
    state["status"] = "Positionsbilder manuell zugeordnet"
    if target_group_id:
        append_log(state, f"Positionsbilder fuer {target_group_id} gespeichert.")
    else:
        append_log(state, f"Positionsbilder manuell zugeordnet: {len(assigned_ids)} Bilder fuer {len(groups)} Beprobungsstellen.")
    save_state(project_id, state)
    return state


def write_image_captions_workbook(path: Path, rows: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Bildtexte"
    ws.append(["Beprobungsstelle", "Bild-ID", "Bildpfad", "Bildtext", "Status"])
    for row in rows:
        ws.append(
            [
                row.get("group_id", ""),
                row.get("image_id", ""),
                row.get("image_path", ""),
                row.get("caption", ""),
                row.get("status", ""),
            ]
        )
    _apply_table_style(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def generate_image_captions(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    assignments = [item for item in state.get("position_image_assignments", []) if item.get("group_id")]
    if not assignments:
        raise ValueError("Bitte zuerst Schritt 12 mit Positionsbildern ausfuehren.")
    captions: list[dict[str, Any]] = []
    for assignment in assignments:
        image_ids = assignment.get("image_ids") or ([assignment.get("image_id", "")] if assignment.get("image_id") else [])
        image_paths = assignment.get("image_paths") or ([assignment.get("image_path", "")] if assignment.get("image_path") else [])
        if not image_paths:
            captions.append(
                {
                    "group_id": assignment.get("group_id", ""),
                    "image_id": "",
                    "image_path": "",
                    "caption": "",
                    "status": "Bildzuordnung offen",
                }
            )
            continue
        for index, image_path in enumerate(image_paths):
            captions.append(
                {
                    "group_id": assignment.get("group_id", ""),
                    "image_id": image_ids[index] if index < len(image_ids) else "",
                    "image_path": image_path,
                    "caption": "",
                    "status": "Text fehlt",
                }
            )

    output = project_dir(project_id) / "04_tables" / "Bildtexte.xlsx"
    write_image_captions_workbook(output, captions)
    state["image_captions"] = captions
    state.setdefault("outputs", {})["image_captions"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Bildtexte vorbereitet"
    append_log(state, f"Bildtextfelder vorbereitet: {len(captions)} Eintraege.")
    save_state(project_id, state)
    return state


def save_image_captions(project_id: str, captions_by_key: dict[str, str]) -> dict[str, Any]:
    state = load_state(project_id)
    assignments = [item for item in state.get("position_image_assignments", []) if item.get("group_id")]
    if not assignments:
        raise ValueError("Bitte zuerst Schritt 12 mit Positionsbildern ausfuehren.")

    rows: list[dict[str, Any]] = []
    for assignment in assignments:
        group_id = assignment.get("group_id", "")
        image_ids = assignment.get("image_ids") or ([assignment.get("image_id", "")] if assignment.get("image_id") else [])
        image_paths = assignment.get("image_paths") or ([assignment.get("image_path", "")] if assignment.get("image_path") else [])
        if not image_paths:
            rows.append(
                {
                    "group_id": group_id,
                    "image_id": "",
                    "image_path": "",
                    "caption": "",
                    "status": "Bildzuordnung offen",
                }
            )
            continue
        for index, image_path in enumerate(image_paths):
            image_id = image_ids[index] if index < len(image_ids) else ""
            caption = captions_by_key.get(f"{group_id}__{image_id}", captions_by_key.get(group_id, "")).strip()
            rows.append(
                {
                    "group_id": group_id,
                    "image_id": image_id,
                    "image_path": image_path,
                    "caption": caption,
                    "status": "Text erfasst" if caption else "Text fehlt",
                }
            )

    output = project_dir(project_id) / "04_tables" / "Bildtexte.xlsx"
    write_image_captions_workbook(output, rows)
    state["image_captions"] = rows
    state.setdefault("outputs", {})["image_captions"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Bildtexte manuell gespeichert"
    append_log(state, f"Bildtexte manuell gespeichert: {sum(1 for row in rows if row.get('caption'))} von {len(rows)} Texten erfasst.")
    save_state(project_id, state)
    return state


def parse_carbonation_rows(text: str) -> list[dict[str, str]]:
    clean = text.strip()
    if not clean:
        return []
    try:
        dialect = csv.Sniffer().sniff(clean[:1000], delimiters="\t;,")
    except csv.Error:
        dialect = csv.excel_tab
    rows = [[cell.strip() for cell in row] for row in csv.reader(StringIO(clean), dialect) if any(cell.strip() for cell in row)]
    if not rows:
        return []
    header = [cell.lower() for cell in rows[0]]
    has_header = any("probe" in cell or "beprob" in cell or "karbon" in cell for cell in header)
    data_rows = rows[1:] if has_header else rows

    def index_for(tokens: list[str], fallback: int) -> int:
        if has_header:
            for idx, cell in enumerate(header):
                if any(token in cell for token in tokens):
                    return idx
        return fallback

    probe_idx = index_for(["probe"], 0)
    group_idx = index_for(["beprob", "bs", "gruppe"], 1)
    carbonation_idx = index_for(["karbon", "carbon"], 2)
    parsed: list[dict[str, str]] = []
    for row in data_rows:
        def get(idx: int) -> str:
            return row[idx].strip() if idx < len(row) else ""

        parsed.append(
            {
                "probe": normalize_probe(get(probe_idx)) if get(probe_idx) else "",
                "group_id": get(group_idx).upper(),
                "carbonation": get(carbonation_idx),
            }
        )
    return [row for row in parsed if row["carbonation"] and (row["probe"] or row["group_id"])]


def save_carbonation_values(project_id: str, text: str) -> dict[str, Any]:
    state = load_state(project_id)
    updates = parse_carbonation_rows(text)
    if not updates:
        raise ValueError("Keine Karbonatisierungswerte erkannt.")
    group_by_probe = _group_by_probe(state.get("sample_groups", []))
    carbonation_by_probe = {row["probe"]: row["carbonation"] for row in updates if row.get("probe")}
    carbonation_by_group = {row["group_id"]: row["carbonation"] for row in updates if row.get("group_id")}
    updated = 0
    measurements = state.get("field_measurements", [])
    for item in measurements:
        probe = item.get("probe", "")
        group_id = group_by_probe.get(probe, "")
        value = carbonation_by_probe.get(probe) or carbonation_by_group.get(group_id)
        if value:
            item["carbonation"] = value
            updated += 1

    output = project_dir(project_id) / "02_processed" / "field_measurements.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_field_workbook(output, measurements)
    state["field_measurements"] = measurements
    state["carbonation_text"] = text
    state["outputs"]["field_measurements"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Karbonatisierung nachgetragen"
    append_log(state, f"Karbonatisierung nachgetragen: {updated} Proben aktualisiert.")
    save_state(project_id, state)
    if state.get("sample_groups"):
        state = generate_sample_groups(project_id)
    return state


def create_export_package(project_id: str) -> dict[str, Any]:
    state = generate_final_report_pdf(project_id)
    outputs = state.get("outputs", {})
    if not outputs:
        raise ValueError("Noch keine Outputs vorhanden.")
    output_path = project_dir(project_id) / "07_export" / "Prototyp_Exportpaket.zip"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for key, relative in sorted(outputs.items()):
            if key == "export_package":
                continue
            source = project_dir(project_id) / relative
            if source.exists() and source.is_file():
                archive.write(source, arcname=f"{key}/{source.name}")
        state_path = project_dir(project_id) / "project_state.json"
        if state_path.exists():
            archive.write(state_path, arcname="project_state.json")
    state.setdefault("outputs", {})["export_package"] = str(output_path.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Finales PDF und Exportpaket erzeugt"
    append_log(state, "Finales PDF und Exportpaket fuer Prototyp erzeugt.")
    save_state(project_id, state)
    return state


def latex_escape(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _format_date(value: str) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if match:
        year, month, day = match.groups()
        return f"{day}.{month}.{year}"
    return text


def _project_label(project: dict[str, Any], key: str, fallback: str) -> str:
    return str(project.get(key) or fallback)


def _latex_table_rows(rows: list[list[Any]]) -> str:
    return "\n".join(" & ".join(latex_escape(cell) for cell in row) + r" \\" for row in rows)


REPORT_PLACEHOLDER = (
    r"\textit{\color{svgray}[Inhalt aus der Vorlage bzw. fachliche Ausarbeitung folgt. "
    r"Messwerte und Bewertungen werden nicht automatisch erzeugt; Prüfung und SV-Freigabe erforderlich.]}"
)

REPORT_SV_NOTE = (
    "Die vorstehende Bewertung ist ein datenbasierter Vorschlag aus dem geprüften Projektstatus. "
    "Fachliche Schlussfolgerung und finale Freigabe bleiben dem Sachverständigen vorbehalten."
)


def extract_template_structure(template_path: Path) -> list[dict[str, Any]]:
    """Liest nur das Ueberschriften-Geruest aus der Word-Vorlage.

    Bewusst werden KEINE Messwerte oder fachlichen Bewertungstexte uebernommen,
    sondern nur die Abschnittsstruktur (siehe 00_global_rules.md: Werte nie erfinden).
    Rueckgabe: Liste aus {"level": 1|2, "title": str}; Heading 1/2 -> Section,
    Heading 3 -> Subsection. Bei Fehlern wird eine leere Liste geliefert, damit
    die Erzeugung auf das interne Standardgeruest zurueckfallen kann.
    """
    try:
        from docx import Document  # lokal, damit processing.py ohne docx importierbar bleibt

        doc = Document(str(template_path))
    except Exception:
        return []
    blocks: list[dict[str, Any]] = []
    for para in doc.paragraphs:
        style = para.style.name if para.style else ""
        title = para.text.strip()
        if not title:
            continue
        if style in {"Title", "Heading 1", "Heading 2"}:
            level = 1
        elif style == "Heading 3":
            level = 2
        else:
            continue
        blocks.append({"level": level, "title": title})
    return blocks


def _default_report_body(frag: dict[str, str]) -> str:
    return "\n".join(
        [
            r"\tableofcontents",
            r"\clearpage",
            r"\section{Auftrag und Aufgabenstellung}",
            frag["auftrag"],
            r"\section{Grundlagen und Unterlagen}",
            frag["grundlagen"],
            r"\section{Objektbeschreibung}",
            frag["objekt"],
            r"\section{Vor-Ort-Erfassung}",
            frag["field_table"],
            r"\section{Fotodokumentation}",
            frag["foto"],
            r"\section{Laborwerte / Ergebnisse}",
            frag["lab_table"],
            r"\section{Bewertung / Beurteilung}",
            frag["bewertung"],
            frag["master_landscape"],
            r"\section{Empfehlung / Maßnahmen}",
            frag["empfehlung"],
            r"\section{Anhang}",
            frag["anhang"],
        ]
    )


def _template_report_body(blocks: list[dict[str, Any]], frag: dict[str, str]) -> str:
    """Baut den Berichtskoerper aus dem Vorlagen-Geruest.

    Geprüfte Projektdaten (Vor-Ort, Labor, Master) werden in die thematisch
    passenden Vorlagen-Abschnitte eingehaengt. Abschnitte ohne Datenzuordnung
    erhalten einen klaren Platzhalter; es werden keine Werte erfunden.
    """
    out: list[str] = [r"\tableofcontents", r"\clearpage"]
    used: set[str] = set()
    current_l1 = ""
    for blk in blocks:
        title = str(blk.get("title", "")).strip()
        if not title:
            continue
        level = 1 if int(blk.get("level", 1)) <= 1 else 2
        tl = title.lower()
        if level == 1:
            current_l1 = tl
            out.append(r"\section{" + latex_escape(title) + "}")
            if "auftrag" in tl:
                out.append(frag["auftrag"])
            elif "grundlagen" in tl:
                out.append(frag["grundlagen"])
                used.add("grundlagen")
            elif "baubeschreibung" in tl or "objekt" in tl:
                out.append(frag["objekt"])
            elif "foto" in tl or "bild" in tl:
                out.append(frag["foto"])
            elif "zusammenfassung" in tl or "schlussfolgerung" in tl:
                out.append(frag["bewertung"])
                if "master" not in used:
                    out.append(frag["master_landscape"])
                    used.add("master")
                out.append(REPORT_SV_NOTE)
            elif "sanierung" in tl or "empfehlung" in tl or "maßnahme" in tl or "massnahme" in tl:
                out.append(frag["empfehlung"])
                used.add("empfehlung")
            elif "anlage" in tl or "anhang" in tl:
                out.append(frag["anhang"])
                used.add("anhang")
            else:
                out.append(REPORT_PLACEHOLDER)
        else:
            out.append(r"\subsection{" + latex_escape(title) + "}")
            if any(k in tl for k in ("beprobungsstelle", "situierung", "beprobung", "probenentnahme")) and "field" not in used:
                out.append(frag["field_table"])
                used.add("field")
            elif "chlorid" in current_l1 and "ergebnis" in tl and "lab" not in used:
                out.append(frag["lab_table"])
                used.add("lab")
            elif "foto" in tl or "bild" in tl:
                out.append(frag["foto"])
            else:
                out.append(REPORT_PLACEHOLDER)
    leftover: list[str] = []
    if "field" not in used:
        leftover += [r"\subsection{Vor-Ort-Erfassung (Projektdaten)}", frag["field_table"]]
    if "lab" not in used:
        leftover += [r"\subsection{Laborwerte / Ergebnisse (Projektdaten)}", frag["lab_table"]]
    if "master" not in used:
        leftover += [r"\subsection{Master-Probenliste (Projektdaten)}", frag["master_landscape"]]
    if leftover:
        out.append(r"\section{Erfasste Projektdaten (Prototyp)}")
        out.append(
            "Die folgenden Tabellen stammen aus dem geprüften Projektstatus und wurden "
            "keiner Überschrift der Vorlage automatisch zugeordnet."
        )
        out.extend(leftover)
    return "\n".join(out)


def build_final_report_latex(
    state: dict[str, Any],
    template_blocks: list[dict[str, Any]] | None = None,
) -> str:
    project = state.get("project", {})
    master = state.get("master_samples", [])
    lab_values = state.get("lab_values", [])
    field_values = state.get("field_measurements", [])
    counts = summary_counts(master)
    title = _project_label(project, "name", "[PROJEKTNAME]")
    address = _project_label(project, "object_address", "[ADRESSE]")
    client = _project_label(project, "client", "[AUFTRAGGEBER]")
    expert = _project_label(project, "expert", "[SACHVERSTAENDIGER]")
    case_worker = _project_label(project, "case_worker", "[SACHBEARBEITER]")
    object_type = _project_label(project, "object_type", "[OBJEKTTYP]")
    inspection_date = _format_date(_project_label(project, "inspection_date", "[DATUM]"))

    field_rows = [
        [
            item.get("probe", ""),
            item.get("position", "[POSITION]"),
            item.get("drill_depth_mm", "[BOHRTIEFE]"),
            item.get("height_cm", "[HOEHE]"),
            item.get("carbonation", "[KARBONATISIERUNG]"),
            item.get("remark", ""),
        ]
        for item in field_values[:12]
    ] or [["[PROBE]", "[POSITION]", "[BOHRTIEFE]", "[HOEHE]", "[KARBONATISIERUNG]", "[BEMERKUNG]"]]

    lab_rows = [
        [
            item.get("probe", ""),
            item.get("sample_label", ""),
            item.get("chloride_display", ""),
            item.get("unit", ""),
            item.get("source", ""),
            item.get("confidence", ""),
        ]
        for item in lab_values
    ]

    master_rows = [
        [
            item.get("probe", ""),
            item.get("position") or "[POSITION]",
            item.get("drill_depth_mm") or "[TIEFE]",
            item.get("height_cm") or "[HOEHE]",
            item.get("chloride_display") or "[LABORWERT]",
            item.get("carbonation") or "[KARBONATISIERUNG]",
            item.get("rating") or "[BEWERTUNG]",
            item.get("status") or "",
        ]
        for item in master
    ]

    frag = {
        "auftrag": rf"""Der unterfertigende Sachverständige wurde mit der materialtechnologischen Überprüfung des Objekts
{latex_escape(address)} befasst. Gegenstand sind Sichtprüfung, Probenzuordnung,
Chloridauswertung, Karbonatisierung, Master-Probenliste, Bewertungsvorschläge und offene Prüfpunkte.""",
        "grundlagen": rf"""\begin{{itemize}}[leftmargin=7mm]
\item Formale Vorlage: GUTACHTEN.docx.
\item Laborwerte: CHLORID ExampleStreet.xlsx bzw. bereinigte Laborwertausgabe.
\item Website-Daten: statischer Workflow unter https://leonrohrer.at/gutachten/.
\item Review: {counts["total"]} Proben, {counts["chloride_over_1"]} Chloridwerte über 1,0 \%, {counts["needs_review"]} offene Prüfpunkte.
\item Regelwerksbezug: ÖNORM B 4706:2015, ÖNORM EN 14629-B, ONR 23303 / ÖNORM B 4710-3.
\end{{itemize}}""",
        "objekt": rf"""\begin{{tabularx}}{{\linewidth}}{{>{{\bfseries}}p{{42mm}}X}}
Objektart & {latex_escape(object_type)}\\
Adresse & {latex_escape(address)}\\
Nutzung & Tiefgarage / Wohnanlage, soweit aus den Projektdaten ableitbar\\
Bauweise & Stahlbeton / massive Bauweise, projektspezifisch zu verifizieren\\
Fehlende Daten & [BAUJAHR], [PLANGRUNDLAGE], [DETAILBESCHREIBUNG]\\
\end{{tabularx}}""",
        "field_table": rf"""\begin{{longtable}}{{p{{15mm}}p{{35mm}}p{{22mm}}p{{18mm}}p{{35mm}}p{{35mm}}}}
\toprule
\rowcolor{{svlight}}\textbf{{Probe}} & \textbf{{Position}} & \textbf{{Tiefe}} & \textbf{{Höhe}} & \textbf{{Karbonatisierung}} & \textbf{{Bemerkung}}\\
\midrule
\endfirsthead
\toprule
\rowcolor{{svlight}}\textbf{{Probe}} & \textbf{{Position}} & \textbf{{Tiefe}} & \textbf{{Höhe}} & \textbf{{Karbonatisierung}} & \textbf{{Bemerkung}}\\
\midrule
\endhead
{_latex_table_rows(field_rows)}
\bottomrule
\end{{longtable}}""",
        "foto": rf"""Für die Fotodokumentation sind Positionsbilder, Schadensbilder, Probenentnahmebilder und
Karbonatisierungsbilder einzufügen. Fehlende Bilddateien sind als [BILDDATEI] zu markieren.""",
        "lab_table": rf"""\begin{{longtable}}{{p{{15mm}}p{{30mm}}p{{25mm}}p{{20mm}}p{{25mm}}p{{22mm}}}}
\toprule
\rowcolor{{svlight}}\textbf{{Probe}} & \textbf{{Bezeichnung}} & \textbf{{Chlorid}} & \textbf{{Einheit}} & \textbf{{Quelle}} & \textbf{{Sicherheit}}\\
\midrule
\endfirsthead
\toprule
\rowcolor{{svlight}}\textbf{{Probe}} & \textbf{{Bezeichnung}} & \textbf{{Chlorid}} & \textbf{{Einheit}} & \textbf{{Quelle}} & \textbf{{Sicherheit}}\\
\midrule
\endhead
{_latex_table_rows(lab_rows)}
\bottomrule
\end{{longtable}}""",
        "bewertung": rf"""\begin{{itemize}}[leftmargin=7mm]
\item Stark kritisch: Chloridwert über 1,0 \%; im Projekt aktuell {counts["chloride_over_1"]} Proben.
\item Prüfung erforderlich: Chloridwert zwischen 0,2 \% und 1,0 \%; im Projekt aktuell {counts["chloride_between_02_1"]} Proben.
\item Normal: Chloridwert unter 0,2 \%, vorbehaltlich Bauteilzustand, Karbonatisierung und Bewehrungslage.
\item Offene Prüfpunkte: {counts["needs_review"]}; fehlende Angaben sind vor finaler Bewertung zu ergänzen.
\end{{itemize}}""",
        "master_landscape": rf"""\begin{{landscape}}
\begin{{longtable}}{{p{{14mm}}p{{36mm}}p{{18mm}}p{{18mm}}p{{22mm}}p{{34mm}}p{{34mm}}p{{58mm}}}}
\toprule
\rowcolor{{svlight}}\textbf{{Probe}} & \textbf{{Position}} & \textbf{{Tiefe}} & \textbf{{Höhe}} & \textbf{{Chlorid}} & \textbf{{Karbonatisierung}} & \textbf{{Bewertung}} & \textbf{{Status}}\\
\midrule
\endfirsthead
\toprule
\rowcolor{{svlight}}\textbf{{Probe}} & \textbf{{Position}} & \textbf{{Tiefe}} & \textbf{{Höhe}} & \textbf{{Chlorid}} & \textbf{{Karbonatisierung}} & \textbf{{Bewertung}} & \textbf{{Status}}\\
\midrule
\endhead
{_latex_table_rows(master_rows)}
\bottomrule
\end{{longtable}}
\end{{landscape}}""",
        "empfehlung": rf"""\begin{{enumerate}}[leftmargin=8mm]
\item Offene Probenpositionen, Bohrtiefen, Höhen und Karbonatisierungen vervollständigen.
\item Fotodokumentation jeder Beprobungsstelle eindeutig zuordnen.
\item Kritische Chloridbereiche bauteilbezogen gruppieren und mit Schadbildern abgleichen.
\item Korrosionszustand und Bewehrungsüberdeckung fachlich prüfen.
\item Sanierungskonzept mit Planung und Ausschreibung abstimmen.
\item Finalfassung erst nach SV-Freigabe ausgeben.
\end{{enumerate}}""",
        "anhang": rf"""\subsection{{Output-Dateien}}
\begin{{itemize}}[leftmargin=7mm]
\item Gutachten\_Final.tex
\item Gutachten\_Final.pdf
\item Master-Probenliste und Gutachtentabellen
\item Review-Bericht
\item project\_state.json
\end{{itemize}}""",
    }
    body = (
        _template_report_body(template_blocks, frag)
        if template_blocks
        else _default_report_body(frag)
    )
    header = rf"""\documentclass[11pt,a4paper]{{article}}
\usepackage[T1]{{fontenc}}
\usepackage[utf8]{{inputenc}}
\usepackage[ngerman]{{babel}}
\usepackage{{lmodern}}
\usepackage{{microtype}}
\usepackage{{geometry}}
\usepackage{{array}}
\usepackage{{booktabs}}
\usepackage{{longtable}}
\usepackage{{tabularx}}
\usepackage[table]{{xcolor}}
\usepackage{{fancyhdr}}
\usepackage{{lastpage}}
\usepackage{{enumitem}}
\usepackage{{titlesec}}
\usepackage{{pdflscape}}
\usepackage[hidelinks]{{hyperref}}
\geometry{{left=24mm,right=24mm,top=25mm,bottom=28mm,headheight=15pt}}
\definecolor{{svblue}}{{HTML}}{{173B57}}
\definecolor{{svlight}}{{HTML}}{{EEF4F8}}
\definecolor{{crit}}{{HTML}}{{B42318}}
\definecolor{{warn}}{{HTML}}{{9A5B00}}
\definecolor{{okgreen}}{{HTML}}{{1B6B45}}
\definecolor{{svgray}}{{HTML}}{{7A7D80}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{6pt}}
\renewcommand{{\arraystretch}}{{1.16}}
\pagestyle{{fancy}}
\fancyhf{{}}
\lhead{{\small Gutachten - {latex_escape(title)}}}
\rhead{{\small \leftmark}}
\cfoot{{\small Seite \thepage\ von \pageref{{LastPage}}}}
\titleformat{{\section}}{{\Large\bfseries\color{{svblue}}}}{{\thesection}}{{0.8em}}{{}}
\titleformat{{\subsection}}{{\large\bfseries}}{{\thesubsection}}{{0.8em}}{{}}
\begin{{document}}
\begin{{titlepage}}
\thispagestyle{{empty}}
\begin{{center}}
{{\color{{svgray}}\rule{{\linewidth}}{{0.45pt}}}}\\[-1mm]
{{\small\bfseries\color{{svgray}} ALLGEMEIN BEEIDETER UND GERICHTLICH ZERTIFIZIERTER SACHVERSTÄNDIGER}}\\[-1mm]
{{\small\bfseries\color{{svgray}} STAATLICH BEFUGTER UND BEEIDETER INGENIEURKONSULENT FÜR BAUINGENIEURWESEN}}\\[3mm]
{{\color{{svgray}}\rule{{\linewidth}}{{0.45pt}}}}
\end{{center}}
\vspace{{4mm}}
\noindent
\begin{{minipage}}[c]{{0.10\linewidth}}
\centering
{{\color{{svgray}}\fbox{{\scriptsize Wappen}}}}
\end{{minipage}}
\begin{{minipage}}[c]{{0.76\linewidth}}
{{\LARGE\bfseries\color{{svgray}} ING. KONS. DIPL.-ING. DR. TECHN. CHRISTOPH NIEDEREGGER}}\\[1mm]
{{\Large\bfseries\color{{svgray}} DI DR. NIEDEREGGER SV\&ZT GMBH}}
\end{{minipage}}
\begin{{minipage}}[c]{{0.12\linewidth}}
\centering
{{\Large\bfseries\color{{svgray}}\fbox{{SV}}}}
\end{{minipage}}

\vspace{{5mm}}
\begin{{center}}
{{\large\color{{svgray}} SCHEIBE 62 A-6167 NEUSTIFT IM STUBAITAL}}\\[-1mm]
\end{{center}}
\noindent
{{\small\color{{svgray}} MOBIL: 0664 4263363}}
\hfill
{{\small\color{{svgray}} EMAIL: \href{{mailto:SV.NIEDEREGGER@EXPERT-GROUP.CC}}{{SV.NIEDEREGGER@EXPERT-GROUP.CC}}}}\\[-1mm]
{{\color{{svgray}}\rule{{\linewidth}}{{0.45pt}}}}

\vspace{{18mm}}
\begin{{center}}
{{\Huge\bfseries\color{{svgray}} G U T A C H T E N}}\\[8mm]
{{\Large Materialtechnologische Untersuchung}}\\[2mm]
{{\Large {latex_escape(object_type)} - {latex_escape(address)}}}
\end{{center}}
\vspace{{10mm}}
\rule{{0.7\linewidth}}{{0.8pt}}\\[12mm]
\begin{{tabularx}}{{\linewidth}}{{>{{\bfseries}}p{{42mm}}X}}
Projekt & {latex_escape(title)}\\
Auftraggeberin & {latex_escape(client)}\\
Objekt & {latex_escape(object_type)}, {latex_escape(address)}\\
Besichtigung & {latex_escape(inspection_date)}\\
Sachverständiger & {latex_escape(expert)}\\
Sachbearbeitung & {latex_escape(case_worker)}\\
Berichtsdatum & [DATUM]\\
Quelle & GUTACHTEN.docx, Laborwerte, Demo-Website https://leonrohrer.at/gutachten/\\
\end{{tabularx}}
\vfill
{{\small Dieses PDF wurde in Schritt 17 automatisch aus den Projekt-, Labor- und Masterdaten erzeugt.
Fachliche Schlussbewertung und finale Freigabe bleiben beim Sachverständigen.}}
\end{{titlepage}}"""
    footer = rf"""

\vspace{{18mm}}
{latex_escape(expert)}\\
\rule{{0.55\linewidth}}{{0.5pt}}\\
Sachverständiger
\end{{document}}
"""
    return header + "\n" + body + "\n" + footer


def _pdf_escape(text: str) -> bytes:
    encoded = str(text).encode("cp1252", errors="replace")
    encoded = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return encoded


class SimplePdf:
    def __init__(self, title: str) -> None:
        self.title = title
        self.width = 595.28
        self.height = 841.89
        self.margin = 46.0
        self.y = self.height - self.margin
        self.pages: list[bytearray] = []
        self.current = bytearray()
        self.page_no = 0
        self.new_page()

    def new_page(self) -> None:
        if self.current:
            self.pages.append(self.current)
        self.current = bytearray()
        self.page_no += 1
        self.y = self.height - self.margin
        if self.page_no > 1:
            self.text(self.margin, self.height - 26, self.title, 8, bold=True, color=(0.09, 0.23, 0.34))
            self.line(self.margin, self.height - 36, self.width - self.margin, self.height - 36, color=(0.78, 0.82, 0.86))
        self.text(self.width - self.margin - 70, 22, f"Seite {self.page_no}", 8, color=(0.35, 0.39, 0.43))

    def finish_page(self) -> None:
        if self.current:
            self.pages.append(self.current)
            self.current = bytearray()

    def cmd(self, value: str | bytes) -> None:
        if isinstance(value, str):
            value = value.encode("ascii")
        self.current.extend(value + b"\n")

    def text(
        self,
        x: float,
        y: float,
        value: str,
        size: float = 10,
        bold: bool = False,
        color: tuple[float, float, float] = (0, 0, 0),
    ) -> None:
        font = "F2" if bold else "F1"
        self.cmd(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg")
        self.cmd(b"BT /" + font.encode("ascii") + f" {size:.1f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ".encode("ascii") + b"(" + _pdf_escape(value) + b") Tj ET")

    def center_text(
        self,
        y: float,
        value: str,
        size: float = 10,
        bold: bool = False,
        color: tuple[float, float, float] = (0, 0, 0),
    ) -> None:
        estimated_width = len(str(value)) * size * 0.52
        self.text((self.width - estimated_width) / 2, y, value, size=size, bold=bold, color=color)

    def line(self, x1: float, y1: float, x2: float, y2: float, color: tuple[float, float, float] = (0, 0, 0)) -> None:
        self.cmd(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG")
        self.cmd(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: tuple[float, float, float] | None = None,
        stroke: tuple[float, float, float] | None = None,
    ) -> None:
        if fill:
            self.cmd(f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg")
            self.cmd(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")
        if stroke:
            self.cmd(f"{stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG")
            self.cmd(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")

    def ensure(self, height: float) -> None:
        if self.y - height < 56:
            self.new_page()

    def write_line(self, value: str, size: float = 10, bold: bool = False, gap: float = 14, color: tuple[float, float, float] = (0, 0, 0)) -> None:
        self.ensure(gap + 4)
        self.text(self.margin, self.y, value, size, bold=bold, color=color)
        self.y -= gap

    def paragraph(self, value: str, size: float = 10, width_chars: int = 92) -> None:
        words = str(value).split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if len(candidate) > width_chars and line:
                self.write_line(line, size=size, gap=size + 4)
                line = word
            else:
                line = candidate
        if line:
            self.write_line(line, size=size, gap=size + 7)

    def section(self, value: str) -> None:
        self.ensure(34)
        self.y -= 6
        self.write_line(value, size=15, bold=True, gap=20, color=(0.09, 0.23, 0.34))
        self.line(self.margin, self.y + 8, self.width - self.margin, self.y + 8, color=(0.83, 0.89, 0.93))

    def key_values(self, rows: list[tuple[str, str]]) -> None:
        label_w = 135
        for label, value in rows:
            self.ensure(18)
            self.text(self.margin, self.y, label, 9, bold=True, color=(0.12, 0.16, 0.2))
            self.text(self.margin + label_w, self.y, value, 9)
            self.y -= 15
        self.y -= 6

    def letterhead(self) -> None:
        gray = (0.47, 0.49, 0.50)
        left = 28.0
        right = self.width - 28.0
        self.line(left, 806, right, 806, color=gray)
        self.center_text(790, "ALLGEMEIN BEEIDETER UND GERICHTLICH ZERTIFIZIERTER SACHVERSTÄNDIGER", 8.5, bold=True, color=gray)
        self.center_text(775, "STAATLICH BEFUGTER UND BEEIDETER INGENIEURKONSULENT FÜR BAUINGENIEURWESEN", 8.5, bold=True, color=gray)
        self.line(left, 748, right, 748, color=gray)

        self.rect(left, 660, 42, 42, stroke=(0.72, 0.74, 0.76))
        self.text(left + 6, 678, "Wappen", 6.5, color=(0.62, 0.64, 0.66))
        self.text(82, 702, "ING. KONS. DIPL.-ING. DR. TECHN. CHRISTOPH NIEDEREGGER", 16, bold=True, color=gray)
        self.text(82, 680, "DI DR. NIEDEREGGER SV&ZT GMBH", 15, bold=True, color=gray)
        self.rect(right - 42, 698, 34, 34, stroke=(0.72, 0.74, 0.76))
        self.text(right - 35, 709, "SV", 14, bold=True, color=gray)

        self.center_text(642, "SCHEIBE 62 A-6167 NEUSTIFT IM STUBAITAL", 9.5, color=gray)
        self.text(left, 626, "MOBIL: 0664 4263363", 7.5, color=gray)
        self.text(330, 626, "EMAIL: SV.NIEDEREGGER@EXPERT-GROUP.CC", 7.5, color=(0.1, 0.25, 0.9))
        self.line(left, 612, right, 612, color=gray)
        self.y = 560

    def table(self, headers: list[str], rows: list[list[Any]], widths: list[float], max_rows: int | None = None) -> None:
        rows = rows[:max_rows] if max_rows else rows
        x0 = self.margin
        row_h = 18
        total_w = sum(widths)
        self.ensure(row_h * 2)
        self.rect(x0, self.y - row_h + 4, total_w, row_h, fill=(0.93, 0.96, 0.98))
        x = x0
        for header, width in zip(headers, widths):
            self.text(x + 3, self.y - 8, header, 7.5, bold=True, color=(0.09, 0.23, 0.34))
            x += width
        self.y -= row_h
        for index, row in enumerate(rows):
            self.ensure(row_h + 4)
            if index % 2:
                self.rect(x0, self.y - row_h + 4, total_w, row_h, fill=(0.98, 0.99, 1.0))
            x = x0
            for cell, width in zip(row, widths):
                text = str(cell or "")
                max_chars = max(4, int(width / 4.2))
                if len(text) > max_chars:
                    text = text[: max_chars - 1] + "…"
                self.text(x + 3, self.y - 8, text, 7.2)
                x += width
            self.line(x0, self.y - row_h + 4, x0 + total_w, self.y - row_h + 4, color=(0.88, 0.9, 0.92))
            self.y -= row_h
        self.y -= 8

    def save(self, path: Path) -> None:
        self.finish_page()
        objects: list[bytes] = []
        page_count = len(self.pages)
        catalog_id = 1
        pages_id = 2
        font_regular_id = 3
        font_bold_id = 4
        next_id = 5
        page_ids: list[int] = []
        content_ids: list[int] = []
        for _ in range(page_count):
            page_ids.append(next_id)
            content_ids.append(next_id + 1)
            next_id += 2
        objects.append(f"{catalog_id} 0 obj << /Type /Catalog /Pages {pages_id} 0 R >> endobj\n".encode("ascii"))
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        objects.append(f"{pages_id} 0 obj << /Type /Pages /Kids [{kids}] /Count {page_count} >> endobj\n".encode("ascii"))
        objects.append(f"{font_regular_id} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n".encode("ascii"))
        objects.append(f"{font_bold_id} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >> endobj\n".encode("ascii"))
        for page_id, content_id, content in zip(page_ids, content_ids, self.pages):
            objects.append(
                (
                    f"{page_id} 0 obj << /Type /Page /Parent {pages_id} 0 R "
                    f"/MediaBox [0 0 {self.width:.2f} {self.height:.2f}] "
                    f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> >> "
                    f"/Contents {content_id} 0 R >> endobj\n"
                ).encode("ascii")
            )
            objects.append(
                f"{content_id} 0 obj << /Length {len(content)} >> stream\n".encode("ascii")
                + bytes(content)
                + b"endstream\nendobj\n"
            )
        pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for obj in objects:
            offsets.append(len(pdf))
            pdf.extend(obj)
        xref = len(pdf)
        pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets[1:]:
            pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        pdf.extend(
            (
                f"trailer << /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n"
            ).encode("ascii")
        )
        path.write_bytes(pdf)


def write_fallback_pdf(path: Path, state: dict[str, Any]) -> None:
    project = state.get("project", {})
    title = _project_label(project, "name", "Gutachten")
    master = state.get("master_samples", [])
    lab_values = state.get("lab_values", [])
    counts = summary_counts(master)
    pdf = SimplePdf(f"Gutachten - {title}")
    pdf.letterhead()
    pdf.center_text(pdf.y, "G U T A C H T E N", size=18, bold=True, color=(0.47, 0.49, 0.50))
    pdf.y -= 34
    pdf.center_text(pdf.y, "Materialtechnologische Untersuchung", size=13, color=(0.12, 0.16, 0.2))
    pdf.y -= 24
    pdf.key_values(
        [
            ("Projekt", title),
            ("Auftraggeberin", _project_label(project, "client", "[AUFTRAGGEBER]")),
            ("Objekt", f"{_project_label(project, 'object_type', '[OBJEKTTYP]')}, {_project_label(project, 'object_address', '[ADRESSE]')}"),
            ("Besichtigung", _format_date(_project_label(project, "inspection_date", "[DATUM]"))),
            ("Sachverständiger", _project_label(project, "expert", "[SACHVERSTAENDIGER]")),
            ("Sachbearbeitung", _project_label(project, "case_worker", "[SACHBEARBEITER]")),
        ]
    )
    pdf.paragraph(
        "Dieses PDF wurde automatisch in Schritt 17 erzeugt. Fachliche Schlussbewertung "
        "und finale Freigabe bleiben beim Sachverständigen."
    )

    pdf.section("Auftrag und Grundlagen")
    pdf.paragraph(
        "Gegenstand sind Sichtprüfung, Probenzuordnung, Chloridauswertung, Karbonatisierung, "
        "Master-Probenliste, Bewertungsvorschläge und offene Prüfpunkte. Als Grundlagen wurden "
        "die Word-Vorlage, Laborwerte, Projektstatus und die Demo-Website ausgewertet."
    )

    pdf.section("Kennzahlen")
    pdf.key_values(
        [
            ("Proben gesamt", str(counts["total"])),
            ("Chlorid > 1,0 %", str(counts["chloride_over_1"])),
            ("Chlorid 0,2 % bis 1,0 %", str(counts["chloride_between_02_1"])),
            ("Offene Prüfpunkte", str(counts["needs_review"])),
        ]
    )

    pdf.section("Laborwerte")
    pdf.table(
        ["Probe", "Bez.", "Chlorid", "Einheit", "Quelle", "Sicherheit"],
        [
            [
                item.get("probe", ""),
                item.get("sample_label", ""),
                item.get("chloride_display", ""),
                item.get("unit", ""),
                item.get("source", ""),
                item.get("confidence", ""),
            ]
            for item in lab_values
        ],
        [40, 90, 65, 55, 80, 70],
    )

    pdf.section("Master-Probenliste")
    pdf.table(
        ["Probe", "Position", "Tiefe", "Chlorid", "Karbon.", "Bewertung", "Status"],
        [
            [
                item.get("probe", ""),
                item.get("position") or "[POSITION]",
                item.get("drill_depth_mm") or "[TIEFE]",
                item.get("chloride_display") or "[LABORWERT]",
                item.get("carbonation") or "[OFFEN]",
                item.get("rating") or "[BEWERTUNG]",
                item.get("status") or "",
            ]
            for item in master
        ],
        [36, 86, 44, 54, 65, 84, 138],
    )

    pdf.section("Bewertung und Maßnahmen")
    pdf.paragraph(
        "Erhöhte Chloridwerte sind bauteilbezogen mit Karbonatisierung, Bewehrungsüberdeckung "
        "und sichtbarem Schadensbild abzugleichen. Offene Angaben sind vor der finalen "
        "Bewertung nachzuführen."
    )
    for item in [
        "Probenpositionen, Bohrtiefen, Höhen und Karbonatisierungen vervollständigen.",
        "Fotodokumentation jeder Beprobungsstelle eindeutig zuordnen.",
        "Kritische Bereiche nach Bauteil, Exposition und Schadbild gruppieren.",
        "Sanierungskonzept mit Planung und Ausschreibung abstimmen.",
    ]:
        pdf.paragraph(f"- {item}", width_chars=86)

    pdf.save(path)


def compile_latex(tex_path: Path, pdf_path: Path) -> bool:
    compiler = shutil.which("lualatex") or shutil.which("pdflatex") or shutil.which("xelatex")
    if not compiler:
        return False
    for _ in range(2):
        result = subprocess.run(
            [compiler, "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
            cwd=tex_path.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            return False
    compiled_pdf = tex_path.with_suffix(".pdf")
    if compiled_pdf.exists():
        if compiled_pdf != pdf_path:
            shutil.copyfile(compiled_pdf, pdf_path)
        return True
    return False


def generate_final_report_pdf(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    if not state.get("master_samples"):
        raise ValueError("Bitte zuerst die Master-Probenliste erzeugen.")
    export_dir = project_dir(project_id) / "07_export"
    export_dir.mkdir(parents=True, exist_ok=True)
    tex_path = export_dir / "Gutachten_Final.tex"
    pdf_path = export_dir / "Gutachten_Final.pdf"

    template_rel = state.get("selected_files", {}).get("template_file")
    template_blocks: list[dict[str, Any]] = []
    if template_rel:
        try:
            template_path = resolve_project_file(project_id, template_rel)
            if template_path.exists():
                template_blocks = extract_template_structure(template_path)
        except Exception:
            template_blocks = []

    tex_path.write_text(build_final_report_latex(state, template_blocks), encoding="utf-8")
    compiled = compile_latex(tex_path, pdf_path)
    if not compiled:
        write_fallback_pdf(pdf_path, state)
    state.setdefault("outputs", {})["report_tex"] = str(tex_path.relative_to(project_dir(project_id)).as_posix())
    state["outputs"]["report_pdf"] = str(pdf_path.relative_to(project_dir(project_id)).as_posix())
    state["pdf_generation"] = {
        "source": state["outputs"]["report_tex"],
        "compiled_with_latex": compiled,
        "pdf": state["outputs"]["report_pdf"],
        "template_structure_used": bool(template_blocks),
        "template_sections": len(template_blocks),
    }
    state["status"] = "Finales PDF erzeugt"
    append_log(
        state,
        "Finales PDF erzeugt."
        if compiled
        else "Finales PDF per internem Fallback erzeugt, weil kein TeX-Compiler verfuegbar war.",
    )
    save_state(project_id, state)
    return state


def style_header(ws: Any) -> None:
    header_fill = PatternFill("solid", fgColor="1F2937")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def write_master_workbook(path: Path, master: list[dict[str, Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Master-Probenliste"
    headers = [
        "Proben-Nr.",
        "Position",
        "Bohrtiefe [mm]",
        "Hoehe [cm]",
        "%Cl(Zement) Masse-%",
        "Karbonatisierung [Tiefe in mm]",
        "Bewertungsvorschlag",
        "Farbe",
        "Status",
    ]
    ws.append(headers)
    fills = {
        "rot": PatternFill("solid", fgColor="FCA5A5"),
        "orange": PatternFill("solid", fgColor="FDBA74"),
        "normal": PatternFill("solid", fgColor="FFFFFF"),
        "pruefen": PatternFill("solid", fgColor="FEF3C7"),
    }
    for item in master:
        row = [
            item.get("probe", ""),
            item.get("position", ""),
            item.get("drill_depth_mm", ""),
            item.get("height_cm", ""),
            item.get("chloride_display", ""),
            item.get("carbonation", ""),
            item.get("rating", ""),
            item.get("color", ""),
            item.get("status", ""),
        ]
        ws.append(row)
        fill = fills.get(item.get("color", "normal"), fills["normal"])
        for cell in ws[ws.max_row]:
            cell.fill = fill
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    style_header(ws)
    autosize(ws)
    wb.save(path)


def _apply_table_style(ws: Any, preserve_fills: bool = False) -> None:
    style_header(ws)
    thin = Side(style="thin", color="D9E1E8")
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        fill = PatternFill("solid", fgColor="F8FAFB" if row[0].row % 2 == 0 else "FFFFFF")
        for cell in row:
            if not preserve_fills:
                cell.fill = fill
            cell.border = Border(bottom=thin)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    autosize(ws)


def write_report_tables_workbook(path: Path, state: dict[str, Any]) -> None:
    master = state.get("master_samples", [])
    lab_by_probe = {item.get("probe"): item for item in state.get("lab_values", [])}
    wb = Workbook()

    ws = wb.active
    ws.title = "Probenzuordnung"
    ws.append(["Probe", "Position", "Bohrtiefe [mm]", "Hoehe [cm]", "Hinweis"])
    for item in master:
        ws.append(
            [
                item.get("probe", ""),
                item.get("position", ""),
                item.get("drill_depth_mm", ""),
                item.get("height_cm", ""),
                item.get("status", ""),
            ]
        )
    _apply_table_style(ws, preserve_fills=True)

    ws = wb.create_sheet("Chloridergebnisse")
    ws.append(["Probe", "%Cl(Zement) Masse-%", "Einheit", "Quelle", "Hinweis"])
    for item in master:
        lab = lab_by_probe.get(item.get("probe"), {})
        ws.append(
            [
                item.get("probe", ""),
                item.get("chloride_display", ""),
                item.get("unit", ""),
                lab.get("source", ""),
                "Laborwert vorhanden" if item.get("chloride_display") else "Chloridwert fehlt",
            ]
        )
    _apply_table_style(ws)

    ws = wb.create_sheet("Bewertung")
    ws.append(["Probe", "Bewertungsvorschlag", "Begruendung", "Status"])
    fills = {
        "rot": PatternFill("solid", fgColor="FCA5A5"),
        "orange": PatternFill("solid", fgColor="FDBA74"),
        "normal": PatternFill("solid", fgColor="FFFFFF"),
        "pruefen": PatternFill("solid", fgColor="FEF3C7"),
    }
    for item in master:
        ws.append(
            [
                item.get("probe", ""),
                item.get("rating", ""),
                item.get("rating_reason", ""),
                item.get("status", ""),
            ]
        )
        fill = fills.get(item.get("color", "normal"), fills["normal"])
        for cell in ws[ws.max_row]:
            cell.fill = fill
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    _apply_table_style(ws)

    for sheet in wb.worksheets:
        sheet.auto_filter.ref = sheet.dimensions
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def generate_report_tables(project_id: str) -> dict[str, Any]:
    state = load_state(project_id)
    if not state.get("master_samples"):
        raise ValueError("Bitte zuerst die Master-Probenliste erzeugen.")
    output = project_dir(project_id) / "04_tables" / "Gutachtentabellen.xlsx"
    write_report_tables_workbook(output, state)
    state.setdefault("outputs", {})["report_tables"] = str(output.relative_to(project_dir(project_id)).as_posix())
    state["status"] = "Gutachtentabellen erzeugt"
    append_log(state, f"Gutachtentabellen erzeugt: {state['outputs']['report_tables']}")
    save_state(project_id, state)
    return state


def summary_counts(master: list[dict[str, Any]]) -> dict[str, int]:
    total = len(master)
    over_1 = sum(1 for item in master if (item.get("chloride_numeric") or 0) > 1.0)
    between = sum(
        1
        for item in master
        if item.get("chloride_numeric") is not None and 0.2 <= item["chloride_numeric"] <= 1.0
    )
    orange = sum(1 for item in master if item.get("color") == "orange")
    missing = sum(1 for item in master if item.get("status") != "ok")
    return {
        "total": total,
        "chloride_over_1": over_1,
        "chloride_between_02_1": between,
        "orange": orange,
        "needs_review": missing,
    }
