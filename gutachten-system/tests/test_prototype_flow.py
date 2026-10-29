from __future__ import annotations

from io import BytesIO
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import main, storage


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path / "projects")
    return TestClient(main.app, raise_server_exceptions=False)


def make_project_state(**overrides):
    state = storage.create_project(
        {
            "project_name": "UX Flow Test",
            "object_address": "Teststrasse 1",
            "client": "Test Auftraggeber",
        }
    )
    state.update(overrides)
    storage.save_state(state["id"], state)
    return state


def complete_state():
    inventory = [
        {
            "path": "00_original/labor/chlorid.xlsx",
            "name": "chlorid.xlsx",
            "extension": ".xlsx",
            "size": 1024,
            "category": "Laborwerte",
        },
        {
            "path": "00_original/notizen/feld.pdf",
            "name": "feld.pdf",
            "extension": ".pdf",
            "size": 1024,
            "category": "Anlage",
        },
        {
            "path": "00_original/vorlage/gutachten.docx",
            "name": "gutachten.docx",
            "extension": ".docx",
            "size": 1024,
            "category": "Gutachtenvorlage",
        },
        {
            "path": "00_original/bilder/IMG001.jpg",
            "name": "IMG001.jpg",
            "extension": ".jpg",
            "size": 1024,
            "category": "Bild",
        },
        {
            "path": "00_original/bilder/IMG002.jpg",
            "name": "IMG002.jpg",
            "extension": ".jpg",
            "size": 1024,
            "category": "Bild",
        },
        {
            "path": "00_original/anlagen/plan.pdf",
            "name": "plan.pdf",
            "extension": ".pdf",
            "size": 1024,
            "category": "Anlage",
        },
    ]
    return make_project_state(
        file_inventory=inventory,
        selected_files={
            "lab_file": "00_original/labor/chlorid.xlsx",
            "field_notes_file": "00_original/notizen/feld.pdf",
            "template_file": "00_original/vorlage/gutachten.docx",
            "image_folder": "00_original/bilder",
            "attachments_folder": "00_original/anlagen/plan.pdf",
        },
        lab_values=[
            {
                "probe": "P01",
                "chloride_display": "1,20",
                "chloride_numeric": 1.2,
                "unit": "Masse-%",
                "source": "Tabelle!A1",
                "confidence": "manuell geprueft",
            }
        ],
        lab_table_accepted=True,
        field_measurements=[
            {
                "probe": "P01",
                "position": "Wand A",
                "drill_depth_mm": "20",
                "height_cm": "10",
                "carbonation": "5 mm",
                "remark": "",
                "status": "ok",
            }
        ],
        sample_groups=[{"group_id": "BS01", "position": "Wand A", "probes": "P01", "status": "Vorschlag ok"}],
        lab_field_merge=[{"probe": "P01", "status": "Verbunden"}],
        master_samples=[
            {
                "probe": "P01",
                "chloride_display": "1,20",
                "chloride_numeric": 1.2,
                "rating": "stark kritisch",
                "color": "rot",
                "status": "ok",
            }
        ],
        marking_proposals=[{"probe": "P01", "color": "rot", "proposal": "Rot vorschlagen"}],
        image_inventory=[
            {
                "image_id": "IMG001",
                "name": "IMG001.jpg",
                "path": "00_original/bilder/IMG001.jpg",
                "use_in_report": True,
                "status": "ausgewaehlt",
            },
            {
                "image_id": "IMG002",
                "name": "IMG002.jpg",
                "path": "00_original/bilder/IMG002.jpg",
                "use_in_report": True,
                "status": "ausgewaehlt",
            },
        ],
        selected_image_ids=["IMG001", "IMG002"],
        position_image_assignments=[
            {
                "group_id": "BS01",
                "position": "Wand A",
                "probes": "P01",
                "image_id": "IMG001",
                "image_path": "00_original/bilder/IMG001.jpg",
                "status": "Vorschlag pruefen",
            }
        ],
        image_captions=[{"group_id": "BS01", "image_path": "00_original/bilder/IMG001.jpg", "caption": "Manueller Bildtext.", "status": "Text erfasst"}],
        carbonation_text="Probe\tKarbonatisierung\nP01\t5 mm",
        outputs={
            "clean_lab_values": "Output/Laborwerte.xlsx",
            "field_measurements": "02_processed/field_measurements.xlsx",
            "sample_groups": "04_tables/sample_groups.xlsx",
            "lab_field_merge": "04_tables/Labor_VorOrt_Verbindung.xlsx",
            "master_samples": "04_tables/Master_Probenliste.xlsx",
            "marking_proposals": "04_tables/Markierungsvorschlaege.xlsx",
            "image_inventory": "04_tables/Bildinventar.xlsx",
            "position_image_assignments": "04_tables/Positionsbilder.xlsx",
            "image_captions": "04_tables/Bildtexte.xlsx",
            "report_tables": "04_tables/Gutachtentabellen.xlsx",
            "review_report": "06_review/Review.txt",
            "report_pdf": "07_export/Gutachten_Final.pdf",
            "export_package": "07_export/Prototyp_Exportpaket.zip",
        },
    )


@pytest.mark.parametrize("step", main.PROTOTYPE_STEPS, ids=lambda step: step["id"])
def test_every_prototype_step_renders_with_status_panel(client, step):
    state = complete_state()

    response = client.get(f"/prototype/{step['id']}?project_id={state['id']}")

    assert response.status_code == 200
    assert step["title"] in response.text
    assert "Workflow-Status" in response.text
    assert "Schritt " in response.text


def test_project_step_validates_required_name_and_disables_submit_until_valid(client):
    page = client.get("/prototype/projekt")
    assert page.status_code == 200
    assert "data-submit-when-valid" in page.text
    assert "Weiter erst nach Projektanlage" in page.text

    response = client.post("/prototype/create-project", data={"project_name": "   "})

    assert response.status_code == 400
    assert "Bitte einen Projektnamen eintragen" in response.text


def test_project_create_preserves_entered_values_in_project_state(client):
    response = client.post(
        "/prototype/create-project",
        data={
            "project_name": "Parkdeck Nord",
            "object_address": "Pruefweg 7",
            "client": "WEG Test",
            "inspection_date": "2026-06-10",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    project_id = response.headers["location"].split("project_id=")[1].split("&")[0]
    state = storage.load_state(project_id)
    assert state["project"]["name"] == "Parkdeck Nord"
    assert state["project"]["object_address"] == "Pruefweg 7"
    assert state["project"]["client"] == "WEG Test"
    assert state["project"]["inspection_date"] == "2026-06-10"


def test_files_step_blocks_next_action_until_inventory_exists(client):
    state = make_project_state()

    response = client.get(f"/prototype/dateien?project_id={state['id']}")

    assert response.status_code == 200
    assert "Import erforderlich" in response.text
    assert "Weiter gesperrt: Dateien klassifizieren" in response.text


def test_files_step_uses_client_side_zip_for_folder_upload(client):
    page = client.get("/prototype/dateien")

    assert page.status_code == 200
    assert 'data-client-zip-folder="true"' in page.text
    assert "Ordner automatisch als ZIP hochladen" in page.text
    assert "Ordner als ZIP importieren" in page.text
    assert "Lokalen Projektordner-Pfad importieren" not in page.text
    assert "20260617-progress" in page.text


def test_folder_upload_route_extracts_zip_and_keeps_archive(client):
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("labor/chlorid.xlsx", "test")
        archive.writestr("bilder/foto.jpg", "test")
    archive_buffer.seek(0)

    response = client.post(
        "/prototype/upload-folder",
        files={"project_files": ("Projektunterlagen.zip", archive_buffer, "application/zip")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    project_id = response.headers["location"].split("project_id=")[1].split("&")[0]
    state = storage.load_state(project_id)
    paths = {item["path"] for item in state["file_inventory"]}
    assert "00_original/_archive/Projektunterlagen.zip" in paths
    assert "00_original/extracted/Projektunterlagen/labor/chlorid.xlsx" in paths
    assert "00_original/extracted/Projektunterlagen/bilder/foto.jpg" in paths
    assert state["last_upload"]["archives"] == 1
    assert state["last_upload"]["extracted"] == 2


def test_folder_upload_accepts_more_than_thousand_files(client):
    # Echte Gutachtenordner (Fotodokumentation) sprengen Starlettes Standardgrenze
    # von 1000 Dateien. Der Ordner-Upload muss das ohne stilles HTTP-400 verkraften.
    files = [
        ("project_files", (f"GrosserOrdner/img/foto_{index}.jpg", BytesIO(b"x"), "image/jpeg"))
        for index in range(1050)
    ]

    response = client.post("/prototype/upload-folder", files=files, follow_redirects=False)

    assert response.status_code == 303
    project_id = response.headers["location"].split("project_id=")[1].split("&")[0]
    state = storage.load_state(project_id)
    assert state["last_upload"]["imported"] == 1050


def test_import_folder_path_copies_local_folder(client, tmp_path):
    # Schneller Direktimport: Backend kopiert einen Ordner vom Dateisystem statt
    # ihn als Browser-Upload entgegenzunehmen.
    source = tmp_path / "Quelle" / "Projektordner"
    (source / "img").mkdir(parents=True)
    (source / "labor").mkdir(parents=True)
    (source / "GUTACHTEN.docx").write_text("doc", encoding="utf-8")
    (source / "labor" / "CHLORID.xlsx").write_text("lab", encoding="utf-8")
    (source / "img" / "foto.jpg").write_bytes(b"x")

    response = client.post(
        "/prototype/import-folder-path",
        data={"folder_path": str(source)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    project_id = response.headers["location"].split("project_id=")[1].split("&")[0]
    state = storage.load_state(project_id)
    paths = {item["path"] for item in state["file_inventory"]}
    assert "00_original/Projektordner/GUTACHTEN.docx" in paths
    assert "00_original/Projektordner/labor/CHLORID.xlsx" in paths
    assert "00_original/Projektordner/img/foto.jpg" in paths
    assert state["last_upload"]["imported"] == 3


def test_old_project_detail_redirects_into_workflow(client):
    # B11: Die alte project.html-Oberflaeche ist abgeloest; alte Links
    # muessen in den 17-Schritte-Workflow umleiten.
    state = make_project_state()

    response = client.get(f"/projects/{state['id']}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/prototype/dateien?project_id={state['id']}"


def test_download_route_still_serves_files(client):
    state = make_project_state()
    target = storage.project_dir(state["id"]) / "Output" / "test.txt"
    target.write_text("ok", encoding="utf-8")

    response = client.get(f"/projects/{state['id']}/download?path=Output/test.txt")

    assert response.status_code == 200
    assert response.text == "ok"


def test_hero_export_cta_only_with_active_project(client):
    # B8: Ohne aktives Projekt darf der zweite Hero-CTA nicht in den
    # gesperrten Schritt 17 fuehren.
    without_project = client.get("/prototype")
    state = make_project_state()
    with_project = client.get(f"/prototype?project_id={state['id']}")

    assert "/prototype/export" not in without_project.text.split("backend-cta")[1].split("</div>")[0]
    assert "Wie es funktioniert" in without_project.text
    assert f"/prototype/export?project_id={state['id']}" in with_project.text


def test_post_redirects_target_workflow_anchor_and_show_saved_banner(client):
    # B4: Nach jedem Submit soll der Nutzer wieder im Arbeitsbereich landen
    # (#workflow-Anker) und eine Gespeichert-Bestaetigung sehen.
    response = client.post(
        "/prototype/create-project",
        data={"project_name": "Anker Test"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("&saved=1#workflow")

    page = client.get(response.headers["location"].split("#")[0])
    assert "Gespeichert" in page.text


def test_existing_projects_listed_on_project_step(client):
    # B3: Vorhandene Projekte muessen auf der Startseite wiederauffindbar sein.
    first = make_project_state()
    second = make_project_state()

    page = client.get("/prototype/projekt")

    assert page.status_code == 200
    assert "Vorhandene Projekte" in page.text
    assert "Weiterarbeiten" in page.text
    assert f"project_id={first['id']}" in page.text
    assert f"project_id={second['id']}" in page.text


def test_start_statistics_renders_clickable_daily_details(client):
    first = make_project_state(
        file_inventory=[{"path": "00_original/a.pdf"}],
        lab_values=[{"probe": "P01"}],
        log=[{"time": "2026-06-20T09:15:00", "message": "Dateien importiert."}],
    )
    second = make_project_state(
        file_inventory=[{"path": "00_original/b.pdf"}, {"path": "00_original/c.pdf"}],
        outputs={"report_pdf": "07_export/Gutachten_Final.pdf"},
        log=[{"time": "2026-06-21T10:30:00", "message": "Exportpaket erzeugt."}],
    )

    page = client.get("/prototype")

    assert page.status_code == 200
    assert 'href="#statistik"' in page.text
    assert "Tagesansicht" in page.text
    assert 'data-stat-day="2026-06-20"' in page.text
    assert 'data-stat-day="2026-06-21"' in page.text
    assert 'data-stat-detail="2026-06-20"' in page.text
    assert "Dateien importiert." in page.text
    assert "Exportpaket erzeugt." in page.text
    assert f"/prototype/dateien?project_id={first['id']}" in page.text
    assert f"/prototype/dateien?project_id={second['id']}" in page.text


def test_last_active_project_restored_from_cookie(client):
    state = make_project_state()

    with_param = client.get(f"/prototype/dateien?project_id={state['id']}")
    without_param = client.get("/prototype/dateien")

    assert with_param.status_code == 200
    assert without_param.status_code == 200
    assert "UX Flow Test" in without_param.text
    assert "Noch kein aktives Projekt" not in without_param.text


def test_validation_error_renders_html_error_page(client):
    # B2: Browser-Formulare bekommen eine gestaltete Fehlerseite mit
    # Zurueck-Link statt einer rohen JSON-Antwort.
    response = client.post(
        "/prototype/create-project",
        data={"project_name": "   "},
        headers={"accept": "text/html"},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Bitte einen Projektnamen eintragen" in response.text
    assert "Zurueck zum Schritt" in response.text


def test_api_error_keeps_json_for_json_clients(client):
    response = client.post(
        "/prototype/onsite/gibt-es-nicht/sync",
        json={},
        headers={"accept": "application/json"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Projekt nicht gefunden"}


def test_upload_into_existing_project_keeps_master_data(client):
    # B1: Ein Upload mit aktiver project_id darf kein neues Projekt anlegen,
    # sondern muss in das bestehende Projekt mit seinen Stammdaten importieren.
    state = make_project_state()

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("labor/chlorid.xlsx", "test")
    archive_buffer.seek(0)

    response = client.post(
        "/prototype/upload",
        data={"project_id": state["id"]},
        files={"gutachten_file": ("Unterlagen.zip", archive_buffer, "application/zip")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert f"project_id={state['id']}" in response.headers["location"]
    saved = storage.load_state(state["id"])
    assert saved["project"]["name"] == "UX Flow Test"
    assert saved["project"]["object_address"] == "Teststrasse 1"
    assert any("chlorid.xlsx" in item["path"] for item in saved["file_inventory"])


def test_folder_upload_into_existing_project_keeps_master_data(client):
    state = make_project_state()

    response = client.post(
        "/prototype/upload-folder",
        data={"project_id": state["id"]},
        files=[("project_files", ("Ordner/img/foto.jpg", BytesIO(b"x"), "image/jpeg"))],
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert f"project_id={state['id']}" in response.headers["location"]
    saved = storage.load_state(state["id"])
    assert saved["project"]["name"] == "UX Flow Test"
    assert saved["last_upload"]["imported"] == 1


def test_import_folder_path_rejects_missing_folder(client):
    response = client.post(
        "/prototype/import-folder-path",
        data={"folder_path": "Z:/gibt/es/nicht"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_classification_requires_all_roles_and_known_paths(client):
    state = complete_state()

    missing = client.post("/prototype/classify", data={"project_id": state["id"]})
    unknown = client.post(
        "/prototype/classify",
        data={
            "project_id": state["id"],
            "lab_file": "00_original/labor/chlorid.xlsx",
            "field_notes_file": "00_original/notizen/feld.pdf",
            "template_file": "00_original/vorlage/gutachten.docx",
            "image_folder": "00_original/bilder",
            "attachments_folder": "00_original/fehlt.pdf",
        },
    )

    assert missing.status_code == 400
    assert "alle wichtigen Dateien" in missing.text
    assert unknown.status_code == 400
    assert "Unbekannte Datei" in unknown.text


def test_classification_saves_values_and_moves_to_lab_step(client):
    state = complete_state()

    response = client.post(
        "/prototype/classify",
        data={
            "project_id": state["id"],
            "lab_file": "00_original/labor/chlorid.xlsx",
            "field_notes_file": "00_original/notizen/feld.pdf",
            "template_file": "00_original/vorlage/gutachten.docx",
            "image_folder": "00_original/bilder",
            "attachments_folder": "00_original/anlagen/plan.pdf",
        },
        follow_redirects=False,
    )

    saved = storage.load_state(state["id"])
    assert response.status_code == 303
    assert response.headers["location"] == f"/prototype/laborwerte?project_id={state['id']}&saved=1#workflow"
    assert saved["selected_files"]["lab_file"] == "00_original/labor/chlorid.xlsx"
    assert saved["status"] == "Dateien klassifiziert"


def test_lab_preview_shows_limit_hint_and_expand_link(client):
    # B6: Die 40x20-Vorschaugrenze muss sichtbar sein und per "Mehr laden"
    # erweiterbar, damit Eingaben jenseits Zeile 40 nicht raetselhaft wirken.
    from openpyxl import Workbook

    state = complete_state()
    lab_path = storage.project_dir(state["id"]) / "00_original" / "labor" / "chlorid.xlsx"
    lab_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    for row in range(1, 60):
        sheet.cell(row=row, column=1, value=f"wert {row}")
    workbook.save(lab_path)

    compact = client.get(f"/prototype/laborwerte?project_id={state['id']}")
    expanded = client.get(f"/prototype/laborwerte?project_id={state['id']}&preview=voll")

    assert "ersten 40 Zeilen" in compact.text
    assert "Mehr laden" in compact.text
    assert "ersten 200 Zeilen" in expanded.text
    assert "Kompakte Vorschau" in expanded.text


def test_lab_step_shows_stage_indicator_without_reaccept_button(client):
    # B9: Der Drei-Stufen-Ablauf ist sichtbar; der verwirrende Button
    # "Erneut akzeptieren" existiert nicht mehr.
    state = complete_state()

    page = client.get(f"/prototype/laborwerte?project_id={state['id']}")

    assert "Zwischentabelle erzeugen" in page.text
    assert "Zwischentabelle akzeptieren" in page.text
    assert "Excel in Output speichern" in page.text
    assert "Erneut akzeptieren" not in page.text


def test_lab_step_shows_missing_classification_and_locks_next_step(client):
    state = make_project_state()

    response = client.get(f"/prototype/laborwerte?project_id={state['id']}")

    assert response.status_code == 200
    assert "Zuerst alle Pflichtdateien in Schritt 3 zuordnen" in response.text
    assert "Weiter gesperrt: Vor-Ort-Werte erfassen" in response.text


def test_field_skip_sets_explicit_unavailable_state_and_feedback(client):
    state = complete_state()

    response = client.post(
        "/prototype/vor-ort/skip",
        data={"project_id": state["id"], "reason": "Keine Baustellendaten geliefert."},
        follow_redirects=False,
    )
    saved = storage.load_state(state["id"])
    page = client.get(f"/prototype/vor-ort?project_id={state['id']}")

    assert response.status_code == 303
    # B10: Skip fuehrt wie Mockdaten/CSV-Import einheitlich zu Schritt 6.
    assert response.headers["location"].startswith(f"/prototype/normalisieren?project_id={state['id']}")
    assert saved["field_measurements_unavailable"]["reason"] == "Keine Baustellendaten geliefert."
    assert "Vor-Ort-Schritt uebersprungen" in page.text
    assert "Keine Baustellendaten geliefert." in page.text


def test_group_generation_route_calls_processing_with_project_id(client, monkeypatch):
    state = complete_state()
    called = {}

    def fake_generate_sample_groups(project_id):
        called["project_id"] = project_id

    monkeypatch.setattr(main, "generate_sample_groups", fake_generate_sample_groups)

    response = client.post(
        "/prototype/gruppieren/generate",
        data={"project_id": state["id"]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/prototype/gruppieren?project_id={state['id']}&saved=1#workflow"
    assert called == {"project_id": state["id"]}


def test_group_generation_reports_missing_field_values(client):
    state = make_project_state(lab_values=[{"probe": "P01"}])

    response = client.post("/prototype/gruppieren/generate", data={"project_id": state["id"]})

    assert response.status_code == 400
    assert "Bitte zuerst Schritt 6" in response.text


def test_image_selection_saves_use_flags_and_blocks_positions_until_selected(client):
    state = complete_state()
    state.pop("selected_image_ids", None)
    for image in state["image_inventory"]:
        image["use_in_report"] = False
    storage.save_state(state["id"], state)

    page = client.get(f"/prototype/bilder?project_id={state['id']}")
    blocked = client.post("/prototype/positionsbilder/generate", data={"project_id": state["id"]})
    selected = client.post(
        "/prototype/bilder/select",
        data={"project_id": state["id"], "selected_image_ids": "IMG001"},
        follow_redirects=False,
    )
    saved = storage.load_state(state["id"])

    assert "Weiter nach Bildauswahl" in page.text
    assert "Alle Bilder auswaehlen" in page.text
    assert "data-image-select-all" in page.text
    assert blocked.status_code == 400
    assert "Bilder fuer das Gutachten auswaehlen" in blocked.text
    assert selected.status_code == 303
    assert saved["selected_image_ids"] == ["IMG001"]
    assert saved["image_inventory"][0]["use_in_report"] is True


def test_manual_image_caption_save_keeps_user_text(client):
    state = complete_state()
    state.pop("image_captions", None)
    storage.save_state(state["id"], state)

    page = client.get(f"/prototype/bildtexte?project_id={state['id']}")
    response = client.post(
        "/prototype/bildtexte/save",
        data={"project_id": state["id"], "caption__BS01__IMG001": "Abbildung 5: Beprobungsstelle BS01 im Bereich Wand A."},
        follow_redirects=False,
    )
    saved = storage.load_state(state["id"])

    assert "Bildtexte schreiben" in page.text
    assert "Bildtexte speichern" in page.text
    assert response.status_code == 303
    assert saved["image_captions"][0]["caption"] == "Abbildung 5: Beprobungsstelle BS01 im Bereich Wand A."
    assert saved["image_captions"][0]["status"] == "Text erfasst"


def test_caption_workbench_saves_one_text_per_assigned_image(client):
    state = complete_state()
    state["position_image_assignments"] = [
        {
            "group_id": "BS01",
            "position": "Wand A",
            "probes": "P01",
            "image_ids": ["IMG001", "IMG002"],
            "image_paths": ["00_original/bilder/IMG001.jpg", "00_original/bilder/IMG002.jpg"],
            "image_id": "IMG001, IMG002",
            "image_path": "00_original/bilder/IMG001.jpg; 00_original/bilder/IMG002.jpg",
            "status": "manuell zugeordnet",
        }
    ]
    state.pop("image_captions", None)
    storage.save_state(state["id"], state)

    page = client.get(f"/prototype/bildtexte?project_id={state['id']}")
    response = client.post(
        "/prototype/bildtexte/save",
        data={
            "project_id": state["id"],
            "caption__BS01__IMG001": "Abbildung 5: Uebersicht BS01.",
            "caption__BS01__IMG002": "Abbildung 6: Detail BS01.",
        },
        follow_redirects=False,
    )
    saved = storage.load_state(state["id"])

    assert "data-caption-workbench" in page.text
    assert "BS01 / IMG001" in page.text
    assert "BS01 / IMG002" in page.text
    assert response.status_code == 303
    assert [row["caption"] for row in saved["image_captions"]] == [
        "Abbildung 5: Uebersicht BS01.",
        "Abbildung 6: Detail BS01.",
    ]
    assert all(row["status"] == "Text erfasst" for row in saved["image_captions"])


def test_saved_caption_renders_confirmation_instead_of_open_editor(client):
    state = complete_state()

    page = client.get(f"/prototype/bildtexte?project_id={state['id']}")

    assert page.status_code == 200
    assert "Bildtext gespeichert" in page.text
    assert "data-caption-confirmation=\"BS01__IMG001\"" in page.text
    assert "data-caption-edit-field=\"BS01__IMG001\" hidden" in page.text
    assert "value=\"Manueller Bildtext.\"" in page.text


def test_manual_position_image_assignment_uses_selected_images(client):
    state = complete_state()

    page = client.get(f"/prototype/positionsbilder?project_id={state['id']}")
    response = client.post(
        "/prototype/positionsbilder/save",
        data={"project_id": state["id"], "image__BS01": "IMG002"},
        follow_redirects=False,
    )
    saved = storage.load_state(state["id"])
    assigned = next(row for row in saved["position_image_assignments"] if row.get("group_id") == "BS01")

    assert "Positionsbilder manuell zuordnen" in page.text
    assert "IMG001" in page.text
    assert "IMG002" in page.text
    assert response.status_code == 303
    assert assigned["image_id"] == "IMG002"
    assert assigned["image_path"] == "00_original/bilder/IMG002.jpg"
    assert assigned["status"] == "manuell zugeordnet"
    assert "image_captions" not in saved


def test_position_image_assignment_allows_multiple_images_per_group_and_prevents_duplicates(client):
    state = complete_state()
    state["sample_groups"] = [
        {"group_id": "BS01", "position": "Wand A", "probes": "P01", "status": "Vorschlag ok"},
        {"group_id": "BS02", "position": "Wand B", "probes": "P02", "status": "Vorschlag ok"},
    ]
    storage.save_state(state["id"], state)

    response = client.post(
        "/prototype/positionsbilder/save",
        data={"project_id": state["id"], "image__BS01": ["IMG001", "IMG002"], "image__BS02": "IMG001"},
        follow_redirects=False,
    )
    saved = storage.load_state(state["id"])
    bs01 = next(row for row in saved["position_image_assignments"] if row.get("group_id") == "BS01")
    bs02 = next(row for row in saved["position_image_assignments"] if row.get("group_id") == "BS02")

    assert response.status_code == 303
    assert bs01["image_ids"] == ["IMG001", "IMG002"]
    assert bs01["image_id"] == "IMG001, IMG002"
    assert bs02["image_ids"] == []
    assert bs02["status"] == "Bildzuordnung offen"


def test_position_image_assignment_can_save_one_group_without_clearing_existing_groups(client):
    state = complete_state()
    state["sample_groups"] = [
        {"group_id": "BS01", "position": "Wand A", "probes": "P01", "status": "Vorschlag ok"},
        {"group_id": "BS02", "position": "Wand B", "probes": "P02", "status": "Vorschlag ok"},
    ]
    state["position_image_assignments"] = [
        {
            "group_id": "BS01",
            "position": "Wand A",
            "probes": "P01",
            "image_ids": ["IMG001"],
            "image_paths": ["00_original/bilder/IMG001.jpg"],
            "image_id": "IMG001",
            "image_path": "00_original/bilder/IMG001.jpg",
            "status": "manuell zugeordnet",
        },
        {
            "group_id": "BS02",
            "position": "Wand B",
            "probes": "P02",
            "image_ids": [],
            "image_paths": [],
            "image_id": "",
            "image_path": "",
            "status": "Bildzuordnung offen",
        },
    ]
    state["image_captions"] = [
        {
            "group_id": "BS01",
            "image_id": "IMG001",
            "image_path": "00_original/bilder/IMG001.jpg",
            "caption": "Bestehender Text BS01.",
            "status": "Text erfasst",
        }
    ]
    storage.save_state(state["id"], state)

    page = client.get(f"/prototype/positionsbilder?project_id={state['id']}")
    response = client.post(
        "/prototype/positionsbilder/save",
        data={"project_id": state["id"], "save_group": "BS02", "image__BS02": "IMG002"},
        follow_redirects=False,
    )
    saved = storage.load_state(state["id"])
    bs01 = next(row for row in saved["position_image_assignments"] if row.get("group_id") == "BS01")
    bs02 = next(row for row in saved["position_image_assignments"] if row.get("group_id") == "BS02")

    assert "name=\"save_group\" value=\"BS01\"" in page.text
    assert "name=\"save_group\" value=\"BS02\"" in page.text
    assert "data-image-id=\"IMG001\" data-group-id=\"BS01\"" in page.text
    assert "data-image-id=\"IMG001\" data-group-id=\"BS02\"" not in page.text
    assert "data-image-id=\"IMG002\" data-group-id=\"BS02\"" in page.text
    assert response.status_code == 303
    assert bs01["image_ids"] == ["IMG001"]
    assert bs02["image_ids"] == ["IMG002"]
    assert saved["image_captions"][0]["caption"] == "Bestehender Text BS01."

    captions_page = client.get(f"/prototype/bildtexte?project_id={state['id']}")
    assert "BS01 / IMG001" in captions_page.text
    assert "BS02 / IMG002" in captions_page.text
    assert "00_original/bilder/IMG002.jpg" in captions_page.text


def test_review_and_export_steps_keep_success_outputs_visible(client):
    state = complete_state()

    review = client.get(f"/prototype/review?project_id={state['id']}")
    export = client.get(f"/prototype/export?project_id={state['id']}")

    assert review.status_code == 200
    assert "Review-Bericht bereit" in review.text
    assert "Review herunterladen" in review.text
    assert export.status_code == 200
    assert "Vorhandene Outputs" in export.text
    assert "PDF-Gutachten laden" in export.text
    assert "report_pdf" in export.text
    assert "export_package" in export.text


def test_export_step_generates_final_pdf_and_package(client):
    state = complete_state()
    state["outputs"].pop("report_pdf", None)
    state["outputs"].pop("export_package", None)
    storage.save_state(state["id"], state)

    response = client.post(
        "/prototype/export/generate",
        data={"project_id": state["id"]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    saved = storage.load_state(state["id"])
    pdf_path = storage.project_dir(state["id"]) / saved["outputs"]["report_pdf"]
    tex_path = storage.project_dir(state["id"]) / saved["outputs"]["report_tex"]
    package_path = storage.project_dir(state["id"]) / saved["outputs"]["export_package"]
    assert pdf_path.exists()
    assert tex_path.exists()
    assert package_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF-")

    page = client.get(f"/prototype/export?project_id={state['id']}")
    assert "PDF-Gutachten laden" in page.text
    assert "07_export/Gutachten_Final.pdf" in page.text


def test_review_step_shows_formatted_browser_preview(client):
    state = complete_state()
    review_path = storage.project_dir(state["id"]) / state["outputs"]["review_report"]
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        "# Review-Bericht\n\n"
        "Dieser Bericht prueft den aktuellen Projektstand.\n\n"
        "## Tabellenpruefung\n"
        "- OK: Keine offensichtlichen Platzhalter gefunden.\n"
        "- WARNUNG: Fachliche Freigabe offen.\n",
        encoding="utf-8",
    )

    response = client.get(f"/prototype/review?project_id={state['id']}")

    assert response.status_code == 200
    assert "Review im Browser" in response.text
    assert '<article class="review-browser-preview"' in response.text
    assert "<h1>Review-Bericht</h1>" in response.text
    assert '<li class="review-item-warning">WARNUNG: Fachliche Freigabe offen.</li>' in response.text


def _report_state():
    return {
        "project": {
            "name": "Demo",
            "object_address": "ExampleStreet 1",
            "object_type": "Tiefgarage",
            "expert": "DI Test",
        },
        "master_samples": [
            {"probe": "P01", "position": "A", "chloride_display": "1,2", "rating": "rot", "status": "ok"}
        ],
        "lab_values": [
            {"probe": "P01", "sample_label": "BS01", "chloride_display": "1,2", "unit": "M-%", "source": "Excel", "confidence": "ok"}
        ],
        "field_measurements": [
            {"probe": "P01", "position": "A", "drill_depth_mm": "20", "height_cm": "100", "carbonation": "5", "remark": ""}
        ],
    }


def test_final_report_latex_uses_template_structure():
    from app import processing

    blocks = [
        {"level": 1, "title": "Auftrag"},
        {"level": 1, "title": "Bestimmung des Chlorideintrages"},
        {"level": 2, "title": "Situierung der Beprobungsstellen"},
        {"level": 2, "title": "Ergebnisse"},
        {"level": 1, "title": "ZUSAMMENFASSUNG"},
        {"level": 1, "title": "Sonderkapitel ohne Daten"},
    ]
    tex = processing.build_final_report_latex(_report_state(), blocks)

    # Struktur stammt aus der Vorlage
    assert r"\section{Bestimmung des Chlorideintrages}" in tex
    assert r"\subsection{Situierung der Beprobungsstellen}" in tex
    # Gepruefte Projektdaten wurden in passende Abschnitte eingehaengt
    assert "P01" in tex and "BS01" in tex
    # Abschnitt ohne Datenzuordnung bekommt klaren Platzhalter, keine erfundenen Werte
    assert "Inhalt aus der Vorlage" in tex
    assert "G U T A C H T E N" in tex  # Briefkopf/Titel bleibt erhalten


def test_final_report_latex_falls_back_without_template():
    from app import processing

    tex = processing.build_final_report_latex(_report_state(), None)
    assert r"\section{Auftrag und Aufgabenstellung}" in tex
    assert "Inhalt aus der Vorlage" not in tex


def test_extract_template_structure_missing_file_is_safe(tmp_path):
    from app import processing

    assert processing.extract_template_structure(tmp_path / "nope.docx") == []
