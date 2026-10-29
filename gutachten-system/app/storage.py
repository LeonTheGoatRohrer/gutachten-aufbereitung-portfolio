from __future__ import annotations

import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO


APP_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = APP_ROOT / "projects"
WORKFLOW_DIR = APP_ROOT / "app" / "workflow_steps"

PROJECT_SUBDIRS = [
    "00_original",
    "01_input",
    "01_working",
    "02_processed",
    "03_images",
    "04_tables",
    "05_report",
    "05_exports",
    "06_review",
    "07_export",
    "Output",
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    value = value.strip().lower()
    replacements = {
        "\u00e4": "ae",
        "\u00f6": "oe",
        "\u00fc": "ue",
        "\u00df": "ss",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "projekt"


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def state_path(project_id: str) -> Path:
    return project_dir(project_id) / "project_state.json"


def ensure_project_dirs(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for subdir in PROJECT_SUBDIRS:
        (path / subdir).mkdir(parents=True, exist_ok=True)


def append_log(state: dict[str, Any], message: str) -> None:
    state.setdefault("log", []).append({"time": now_iso(), "message": message})


def save_state(project_id: str, state: dict[str, Any]) -> None:
    ensure_project_dirs(project_dir(project_id))
    state["updated_at"] = now_iso()
    state_path(project_id).write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_state(project_id: str) -> dict[str, Any]:
    path = state_path(project_id)
    if not path.exists():
        raise FileNotFoundError(project_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_projects() -> list[dict[str, Any]]:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects: list[dict[str, Any]] = []
    for path in sorted(PROJECTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir():
            continue
        state_file = path / "project_state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            state["_id"] = path.name
            projects.append(state)
    return projects


def create_project(data: dict[str, str]) -> dict[str, Any]:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    base_slug = slugify(data.get("project_name") or data.get("object_address") or "projekt")
    project_id = base_slug
    counter = 2
    while project_dir(project_id).exists():
        project_id = f"{base_slug}_{counter}"
        counter += 1

    ensure_project_dirs(project_dir(project_id))
    state: dict[str, Any] = {
        "id": project_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "project": {
            "name": data.get("project_name", "").strip(),
            "object_address": data.get("object_address", "").strip(),
            "client": data.get("client", "").strip(),
            "inspection_date": data.get("inspection_date", "").strip(),
            "expert": data.get("expert", "").strip(),
            "case_worker": data.get("case_worker", "").strip(),
            "object_type": data.get("object_type", "").strip(),
        },
        "selected_files": {},
        "file_inventory": [],
        "lab_values": [],
        "field_measurements": [],
        "master_samples": [],
        "outputs": {},
        "status": "Projekt angelegt",
        "log": [],
    }
    append_log(state, "Projektordner angelegt.")
    save_state(project_id, state)
    return state


def classify_file(path: Path) -> str:
    name = path.name.lower()
    ext = path.suffix.lower()
    if ext == ".zip":
        return "Archiv"
    if ext in {".jpg", ".jpeg", ".png"}:
        return "Bild"
    if ext == ".pdf":
        return "Anlage"
    if ext in {".docx", ".doc"}:
        if "av" == path.stem.lower() or "anlage" in name:
            return "Anlagenverzeichnis"
        if "gutachten" in name or "vorlage" in name:
            return "Gutachtenvorlage"
        return "Word-Dokument"
    if ext in {".xlsx", ".xls", ".xlsm"}:
        if path.name.startswith("~$"):
            return "Temp-Datei"
        if any(token in name for token in ["chlorid", "analyse", "tiqu", "bdb", "befund"]):
            return "Laborwerte"
        if any(token in name for token in ["notiz", "erfasst", "vor_ort", "vor-ort", "mess"]):
            return "Vor-Ort-Werte"
        return "Excel-Datei"
    if ext == ".csv":
        if any(token in name for token in ["chlorid", "analyse", "labor", "befund"]):
            return "Laborwerte"
        return "CSV-Datei"
    if ext in {".msg", ".eml"}:
        return "E-Mail"
    if ext == ".txt":
        return "Text"
    return "Sonstiges"


def inventory_for(project_id: str) -> list[dict[str, Any]]:
    root = project_dir(project_id) / "00_original"
    inventory: list[dict[str, Any]] = []
    if not root.exists():
        return inventory
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project_dir(project_id)).as_posix()
        inventory.append(
            {
                "path": rel,
                "name": path.name,
                "extension": path.suffix.lower(),
                "size": path.stat().st_size,
                "category": classify_file(path),
                "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    return inventory


def safe_copy_file(source: Path, target_root: Path, relative: Path) -> Path:
    target = target_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)
        return target

    stem = target.stem
    suffix = target.suffix
    counter = 2
    while True:
        candidate = target.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            shutil.copy2(source, candidate)
            return candidate
        counter += 1


def safe_write_stream(source: BinaryIO, target_root: Path, relative: Path) -> Path:
    target = target_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        counter = 2
        while True:
            candidate = target.with_name(f"{stem}_{counter}{suffix}")
            if not candidate.exists():
                target = candidate
                break
            counter += 1

    with target.open("wb") as output:
        shutil.copyfileobj(source, output)
    return target


def zip_member_relative_path(member_name: str) -> Path | None:
    cleaned = member_name.replace("\\", "/").strip("/")
    if not cleaned or cleaned.startswith("/") or re.match(r"^[a-zA-Z]:", cleaned):
        return None

    parts = [part for part in cleaned.split("/") if part]
    if not parts or any(part == ".." for part in parts):
        return None
    return Path(*parts)


def upload_relative_path(filename: str) -> Path | None:
    return zip_member_relative_path(filename)


def extract_zip_to_original(archive_path: Path, target_root: Path, base_relative: Path) -> dict[str, int]:
    extracted = 0
    skipped = 0
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            relative = zip_member_relative_path(member.filename)
            if relative is None or (relative.parts and relative.parts[0] == "__MACOSX"):
                skipped += 1
                continue
            with archive.open(member) as source:
                safe_write_stream(source, target_root, base_relative / relative)
            extracted += 1
    return {"extracted": extracted, "skipped": skipped}


def import_uploaded_file(project_id: str, upload_path: Path, original_filename: str) -> dict[str, Any]:
    filename = Path(original_filename or upload_path.name).name
    if not filename:
        raise ValueError("Die hochgeladene Datei hat keinen Dateinamen.")

    target_root = project_dir(project_id) / "00_original"
    target_root.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower()
    import_summary: dict[str, Any] = {
        "filename": filename,
        "uploaded_at": now_iso(),
        "kind": "zip" if suffix == ".zip" else "file",
        "extracted": 0,
        "skipped": 0,
    }

    if suffix == ".zip":
        archive_path = safe_copy_file(upload_path, target_root, Path("_archive") / filename)
        extract_base = Path("extracted") / Path(filename).stem
        zip_stats = extract_zip_to_original(upload_path, target_root, extract_base)
        import_summary.update(zip_stats)
        import_summary["archive_path"] = archive_path.relative_to(project_dir(project_id)).as_posix()
        log_message = (
            f"ZIP hochgeladen: {filename}; "
            f"{zip_stats['extracted']} Dateien entpackt, {zip_stats['skipped']} uebersprungen."
        )
    else:
        saved_path = safe_copy_file(upload_path, target_root, Path(filename))
        import_summary["saved_path"] = saved_path.relative_to(project_dir(project_id)).as_posix()
        log_message = f"Datei hochgeladen: {filename}."

    state = load_state(project_id)
    state["file_inventory"] = inventory_for(project_id)
    state["last_upload"] = import_summary
    state["status"] = "Dateien importiert"

    lab_candidates = [item for item in state["file_inventory"] if item["category"] == "Laborwerte"]
    template_candidates = [item for item in state["file_inventory"] if item["category"] == "Gutachtenvorlage"]
    if lab_candidates and not state.get("selected_files", {}).get("lab_file"):
        state.setdefault("selected_files", {})["lab_file"] = lab_candidates[0]["path"]
    if template_candidates and not state.get("selected_files", {}).get("template_file"):
        state.setdefault("selected_files", {})["template_file"] = template_candidates[0]["path"]

    append_log(state, log_message)
    save_state(project_id, state)
    return state


def import_uploaded_files(project_id: str, uploaded_files: list[tuple[Path, str]]) -> dict[str, Any]:
    target_root = project_dir(project_id) / "00_original"
    target_root.mkdir(parents=True, exist_ok=True)

    imported = 0
    skipped = 0
    archives = 0
    extracted = 0
    for source_path, original_filename in uploaded_files:
        relative = upload_relative_path(original_filename)
        if relative is None:
            skipped += 1
            continue
        if source_path.suffix.lower() == ".zip":
            safe_copy_file(source_path, target_root, Path("_archive") / relative)
            extract_base = Path("extracted") / relative.with_suffix("")
            zip_stats = extract_zip_to_original(source_path, target_root, extract_base)
            archives += 1
            extracted += zip_stats["extracted"]
            skipped += zip_stats["skipped"]
        else:
            safe_copy_file(source_path, target_root, relative)
            imported += 1

    state = load_state(project_id)
    state["file_inventory"] = inventory_for(project_id)
    state["last_upload"] = {
        "kind": "folder",
        "uploaded_at": now_iso(),
        "imported": imported,
        "archives": archives,
        "extracted": extracted,
        "skipped": skipped,
    }
    state["status"] = "Dateien importiert"

    lab_candidates = [item for item in state["file_inventory"] if item["category"] == "Laborwerte"]
    template_candidates = [item for item in state["file_inventory"] if item["category"] == "Gutachtenvorlage"]
    if lab_candidates and not state.get("selected_files", {}).get("lab_file"):
        state.setdefault("selected_files", {})["lab_file"] = lab_candidates[0]["path"]
    if template_candidates and not state.get("selected_files", {}).get("template_file"):
        state.setdefault("selected_files", {})["template_file"] = template_candidates[0]["path"]

    append_log(
        state,
        (
            "Projektordner hochgeladen: "
            f"{imported} Dateien importiert, {archives} ZIP-Archive gesichert, "
            f"{extracted} Dateien entpackt, {skipped} uebersprungen."
        ),
    )
    save_state(project_id, state)
    return state


def import_folder(project_id: str, source_folder: str) -> dict[str, Any]:
    source = Path(source_folder).expanduser()
    if not source.exists() or not source.is_dir():
        raise ValueError("Der angegebene Importordner existiert nicht.")

    project_root = project_dir(project_id).resolve()
    source_resolved = source.resolve()
    if source_resolved == project_root or project_root in source_resolved.parents:
        raise ValueError("Der Projektordner selbst kann nicht importiert werden.")

    target_root = project_dir(project_id) / "00_original"
    copied = 0
    skipped = 0
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        try:
            rel = item.relative_to(source)
            safe_copy_file(item, target_root, rel)
            copied += 1
        except OSError:
            skipped += 1

    state = load_state(project_id)
    state["file_inventory"] = inventory_for(project_id)
    state["import_source"] = str(source)
    state["status"] = "Dateien importiert"
    append_log(state, f"Import abgeschlossen: {copied} Dateien kopiert, {skipped} uebersprungen.")
    save_state(project_id, state)
    return state


def resolve_project_file(project_id: str, relative_path: str) -> Path:
    base = project_dir(project_id).resolve()
    path = (project_dir(project_id) / relative_path).resolve()
    if path != base and base not in path.parents:
        raise ValueError("Dateipfad liegt ausserhalb des Projektordners.")
    return path


def output_link(project_id: str, relative_path: str) -> str:
    return f"/projects/{project_id}/download?path={relative_path}"
