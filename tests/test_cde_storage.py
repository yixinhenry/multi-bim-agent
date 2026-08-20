from __future__ import annotations

from pathlib import Path

from bim_multi import storage
from bim_multi.domain import CDEState


def _project(tmp_path: Path) -> tuple[Path, int, Path]:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "P", root)
    return db_path, project_id, root


def test_model_slots_are_unique_and_increment_generation(tmp_path: Path) -> None:
    db_path, project_id, root = _project(tmp_path)
    path = root / "models" / "WIP" / "ARC.ifc"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"v1")

    first = storage.upsert_model_slot(
        db_path,
        project_id,
        "ARC",
        CDEState.WIP,
        path,
        "arc-v1.ifc",
        "ARC-MOD-SHELL",
    )
    second = storage.upsert_model_slot(
        db_path,
        project_id,
        "ARC",
        CDEState.WIP,
        path,
        "arc-v2.ifc",
        "ARC-MOD-INTERIOR",
    )

    assert first["generation"] == 1
    assert second["generation"] == 2
    assert len(storage.model_slots(db_path, project_id)) == 1


def test_legacy_ifc_record_is_registered_as_wip_slot(tmp_path: Path) -> None:
    db_path, project_id, root = _project(tmp_path)
    legacy = root / "ARC.ifc"
    legacy.write_bytes(b"legacy")
    storage.upsert_project_file(db_path, project_id, "ARC", legacy, "legacy.ifc")

    storage.init_db(db_path)

    slot = storage.get_model_slot(db_path, project_id, "ARC", CDEState.WIP)
    assert slot is not None
    assert Path(slot["path"]) == legacy


def test_clash_runs_and_notifications_round_trip(tmp_path: Path) -> None:
    db_path, project_id, _ = _project(tmp_path)
    run_id = storage.create_clash_run(
        db_path,
        project_id,
        [{"discipline": "ARC", "cde_state": "Shared"}],
        {"ARC-MEP": 2},
        {"tolerance": 0.002},
        "PM-BIM",
    )
    run = storage.list_clash_runs(db_path, project_id)[0]
    assert run["id"] == run_id
    assert run["pair_counts"] == {"ARC-MEP": 2}

    notification_id = storage.create_notification(
        db_path,
        project_id,
        "PM-BIM",
        "shared_ready",
        "Two Shared models are available",
        {"disciplines": ["ARC", "MEP"]},
        run_id,
    )
    unread = storage.list_notifications(db_path, project_id, "PM-BIM", unread_only=True)
    assert [item["id"] for item in unread] == [notification_id]
    assert unread[0]["payload"]["disciplines"] == ["ARC", "MEP"]
    assert storage.mark_notification_read(db_path, project_id, notification_id)
    assert storage.list_notifications(db_path, project_id, "PM-BIM", unread_only=True) == []
