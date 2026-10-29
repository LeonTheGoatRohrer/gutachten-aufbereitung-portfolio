"""Schritt 5 - Vor-Ort-Erfassung (OnSiteCapture).

Dieser Modul nimmt die im Browser (IndexedDB) erfassten Vor-Ort-Daten entgegen
und legt sie dauerhaft im Projekt ab. Die eigentliche Erfassung passiert
offline-faehig im Client; hier wird nur synchronisiert/gespeichert.

Bewusst NICHT Teil dieses Schritts: Laborauswertung, Endtabelle, Gutachten,
KI-Karbonatisierung, fachliche Endbewertung.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from .storage import append_log, load_state, now_iso, project_dir, save_state
from .processing import write_field_workbook

ONSITE_JSON_RELATIVE = "02_processed/onsite_capture.json"
ONSITE_IMAGE_DIR = "03_images/onsite"

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w/.+-]+);base64,(?P<data>.+)$", re.DOTALL)
_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/gif": ".gif",
}


def _safe_segment(value: Any, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    text = text.strip("_")
    return text or fallback


def _decode_data_url(data_url: str) -> tuple[bytes, str] | None:
    match = _DATA_URL_RE.match(data_url or "")
    if not match:
        return None
    try:
        raw = base64.b64decode(match.group("data"), validate=False)
    except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
        return None
    ext = _MIME_EXT.get(match.group("mime").lower(), ".bin")
    return raw, ext


def _write_photo(project_id: str, photo: dict[str, Any]) -> str | None:
    """Schreibt ein base64-Foto auf die Platte und liefert den relativen Pfad."""
    data_url = photo.get("dataUrl") or photo.get("data") or ""
    decoded = _decode_data_url(data_url)
    if decoded is None:
        # Schon eine Referenz (z. B. bereits synchronisiert) -> unveraendert lassen.
        return photo.get("file") or photo.get("fileUrl")
    raw, ext = decoded
    location_seg = _safe_segment(photo.get("samplingLocationNumber") or photo.get("samplingLocationId"), "ohne_bs")
    photo_seg = _safe_segment(photo.get("id"), "foto")
    rel_dir = Path(ONSITE_IMAGE_DIR) / location_seg
    target_dir = project_dir(project_id) / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{photo_seg}{ext}"
    target.write_bytes(raw)
    return (rel_dir / target.name).as_posix()


def _counts(payload: dict[str, Any]) -> dict[str, int]:
    locations = payload.get("samplingLocations", []) or []
    samples = payload.get("samples", []) or []
    photos = payload.get("photos", []) or []
    reviewed = sum(1 for loc in locations if str(loc.get("status", "")).lower() in {"geprueft", "geprüft", "vollstaendig", "vollständig"})
    return {
        "locations": len(locations),
        "samples": len(samples),
        "photos": len(photos),
        "locations_ready": reviewed,
        "warnings": len(payload.get("validationWarnings", []) or []),
    }


def _location_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(location.get("id")): location
        for location in payload.get("samplingLocations", []) or []
        if location.get("id")
    }


def _carbonation_value(location: dict[str, Any]) -> str:
    depth = str(location.get("carbonationDepth") or "").strip()
    special = str(location.get("carbonationSpecialValue") or "").strip()
    comment = str(location.get("carbonationComment") or "").strip()
    parts = [part for part in [depth, special, comment] if part]
    return " | ".join(parts)


def _field_measurements_from_onsite(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Leitet die klassische Vor-Ort-Tabelle aus der mobilen Erfassung ab."""
    locations = _location_lookup(payload)
    measurements: list[dict[str, Any]] = []
    for sample in payload.get("samples", []) or []:
        location = locations.get(str(sample.get("samplingLocationId")), {})
        position = str(location.get("position") or "").strip()
        loc_comment = str(location.get("comment") or "").strip()
        sample_comment = str(sample.get("comment") or "").strip()
        note_type = str(sample.get("noteType") or "").strip()
        remarks = [part for part in [loc_comment, note_type if note_type != "keiner" else "", sample_comment] if part]
        uncertain = bool(location.get("positionUncertain"))
        status = str(sample.get("status") or "").strip()
        loc_status = str(location.get("status") or "").strip()
        if uncertain or loc_status in {"offen", "unvollstaendig"}:
            status = "Pruefung erforderlich"
        measurements.append(
            {
                "probe": str(sample.get("sampleNumber") or "").strip(),
                "position": position,
                "drill_depth_mm": str(sample.get("drillingDepthMm") or "").strip(),
                "height_cm": str(sample.get("heightCm") or "").strip() or "-",
                "carbonation": _carbonation_value(location),
                "remark": " | ".join(remarks),
                "status": status or "erfasst",
            }
        )
    measurements.sort(key=lambda item: item["probe"])
    return measurements


def sync_onsite_capture(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persistiert die Vor-Ort-Erfassung dauerhaft im Projekt.

    - Fotos (base64) werden als Dateien unter 03_images/onsite/<BS>/ abgelegt.
    - Das JSON (ohne base64-Rohdaten) wird unter 02_processed/onsite_capture.json gespeichert.
    - project_state.json bekommt einen Verweis und eine kurze Zusammenfassung.
    """
    state = load_state(project_id)  # wirft FileNotFoundError, wenn Projekt fehlt

    stored = json.loads(json.dumps(payload))  # tiefe Kopie
    stored["projectId"] = project_id
    stored["syncedAt"] = now_iso()

    for photo in stored.get("photos", []) or []:
        rel = _write_photo(project_id, photo)
        if rel:
            photo["file"] = rel
        # base64-Rohdaten nicht dauerhaft im JSON behalten (zu gross).
        photo.pop("dataUrl", None)
        photo.pop("data", None)

    json_path = project_dir(project_id) / ONSITE_JSON_RELATIVE
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding="utf-8")

    measurements = _field_measurements_from_onsite(stored)
    field_output = project_dir(project_id) / "02_processed" / "field_measurements.xlsx"
    field_output.parent.mkdir(parents=True, exist_ok=True)
    write_field_workbook(field_output, measurements)

    counts = _counts(stored)
    state.setdefault("outputs", {})["onsite_capture"] = ONSITE_JSON_RELATIVE
    state["outputs"]["field_measurements"] = str(field_output.relative_to(project_dir(project_id)).as_posix())
    state["field_measurements"] = measurements
    state["onsite_summary"] = {**counts, "synced_at": stored["syncedAt"]}
    state["status"] = "Vor-Ort-Daten erfasst"
    append_log(
        state,
        "Vor-Ort-Erfassung synchronisiert: "
        f"{counts['locations']} Beprobungsstellen, {counts['samples']} Proben, "
        f"{counts['photos']} Fotos, {len(measurements)} Vor-Ort-Zeilen.",
    )
    save_state(project_id, state)
    return {"saved": ONSITE_JSON_RELATIVE, "counts": counts, "synced_at": stored["syncedAt"]}


def load_onsite_capture(project_id: str) -> dict[str, Any] | None:
    path = project_dir(project_id) / ONSITE_JSON_RELATIVE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
