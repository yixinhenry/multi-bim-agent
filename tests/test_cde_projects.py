from __future__ import annotations

from io import BytesIO
from pathlib import Path

from bim_multi import projects, storage
from bim_multi.domain import CDEState


def _project(tmp_path: Path) -> tuple[Path, int, Path]:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "P", root)
    return db_path, project_id, root


def _upload(db_path: Path, project_id: int, discipline: str, payload: bytes) -> Path:
    return projects.save_upload(
        db_path,
        project_id,
        discipline,
        f"{discipline.lower()}.ifc",
        BytesIO(payload),
        uploaded_by=f"{discipline}-MOD",
    )


def test_wip_upload_uses_stable_slot_and_clears_cache(tmp_path: Path) -> None:
    db_path, project_id, root = _project(tmp_path)
    target = _upload(db_path, project_id, "ARC", b"v1")
    assert target == root / "models" / "WIP" / "ARC.ifc"
    target.with_suffix(".frag").write_bytes(b"cache")

    _upload(db_path, project_id, "ARC", b"v2")

    slot = storage.get_model_slot(db_path, project_id, "ARC", CDEState.WIP)
    assert slot is not None and slot["generation"] == 2
    assert target.read_bytes() == b"v2"
    assert not target.with_suffix(".frag").exists()


def test_cost_and_schedule_uploads_use_independent_records(tmp_path: Path) -> None:
    db_path, project_id, root = _project(tmp_path)
    projects.save_upload(
        db_path, project_id, "COST", "cost.csv", BytesIO(b"Item,Cost\nA,1")
    )
    projects.save_upload(
        db_path,
        project_id,
        "SCHEDULE",
        "schedule.csv",
        BytesIO(b"Task,Progress\nA,50"),
    )

    records = storage.project_files(db_path, project_id)
    assert set(records) == {"COST", "SCHEDULE"}
    assert Path(records["COST"]["path"]) == root / "Cost.csv"
    assert Path(records["SCHEDULE"]["path"]) == root / "Schedule.csv"


def test_shared_notifications_are_condensed_by_transition(tmp_path: Path) -> None:
    db_path, project_id, _ = _project(tmp_path)
    for discipline in projects.DISCIPLINES:
        _upload(db_path, project_id, discipline, discipline.encode())

    projects.submit_shared(db_path, project_id, "ARC", "ARC-LEAD")
    assert storage.list_notifications(db_path, project_id, "PM-BIM") == []

    projects.submit_shared(db_path, project_id, "MEP", "MEP-LEAD")
    projects.submit_shared(db_path, project_id, "STR", "STR-LEAD")
    projects.submit_shared(db_path, project_id, "ARC", "ARC-LEAD")

    notifications = storage.list_notifications(db_path, project_id, "PM-BIM")
    assert [item["notification_type"] for item in notifications] == [
        "shared_updated",
        "shared_ready",
        "shared_ready",
    ]


def test_publish_rotates_one_archived_slot_and_manual_archive_copies(tmp_path: Path) -> None:
    db_path, project_id, _ = _project(tmp_path)
    _upload(db_path, project_id, "ARC", b"v1")
    projects.submit_shared(db_path, project_id, "ARC", "ARC-LEAD")
    projects.publish_model(db_path, project_id, "ARC", "PM-BIM")

    _upload(db_path, project_id, "ARC", b"v2")
    projects.submit_shared(db_path, project_id, "ARC", "ARC-LEAD")
    projects.publish_model(db_path, project_id, "ARC", "PM-BIM")

    _, published, _ = projects.resolve_model_slot(
        db_path, project_id, "ARC", CDEState.PUBLISHED
    )
    _, archived, _ = projects.resolve_model_slot(
        db_path, project_id, "ARC", CDEState.ARCHIVED
    )
    assert published.read_bytes() == b"v2"
    assert archived.read_bytes() == b"v1"

    projects.archive_model(db_path, project_id, "ARC", "PM-BIM")
    assert published.read_bytes() == b"v2"
    assert archived.read_bytes() == b"v2"
    arc_slots = [key for key in storage.model_slots(db_path, project_id) if key[0] == "ARC"]
    assert len(arc_slots) == 4
