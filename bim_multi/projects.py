from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from . import storage
from .domain import CDEState


DISCIPLINES = ("ARC", "STR", "MEP")
KINDS = (*DISCIPLINES, "COST", "SCHEDULE")
FILENAMES = {
    "ARC": "ARC.ifc",
    "STR": "STR.ifc",
    "MEP": "MEP.ifc",
    "COST": "Cost.csv",
    "SCHEDULE": "Schedule.csv",
}


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", name.strip(), flags=re.UNICODE).strip("._")
    return cleaned[:80] or "project"


def create(db_path: Path, projects_dir: Path, name: str) -> int:
    projects_dir.mkdir(parents=True, exist_ok=True)
    root = projects_dir / f"{safe_name(name)}_{uuid4().hex[:8]}"
    root.mkdir()
    return storage.create_project(db_path, name.strip(), root)


def model_slot_path(root: Path, discipline: str, cde_state: CDEState) -> Path:
    return root / "models" / cde_state.value / FILENAMES[discipline]


def _write_upload(target: Path, source: BinaryIO) -> None:
    payload = source.read()
    if not payload:
        raise ValueError("Uploaded file is empty")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".upload")
    temporary.write_bytes(payload)
    temporary.replace(target)
    target.with_suffix(".frag").unlink(missing_ok=True)


def _audit_slot_action(
    db_path: Path,
    project_id: int,
    role: str | None,
    operation: str,
    discipline: str,
    source_state: CDEState | None,
    target_state: CDEState,
    overwritten: bool,
) -> None:
    storage.add_audit_event(
        db_path,
        {
            "project_id": project_id,
            "agent_id": "application",
            "declared_role": role or "SYSTEM",
            "target_file": f"{discipline}/{target_state.value}",
            "operation": operation,
            "tool_parameters": {
                "discipline": discipline,
                "source_state": source_state.value if source_state else None,
                "target_state": target_state.value,
                "overwritten": overwritten,
            },
            "result_summary": f"{discipline} {target_state.value} slot updated",
            "status": "completed",
        },
    )


def save_upload(
    db_path: Path,
    project_id: int,
    kind: str,
    original_filename: str,
    source: BinaryIO,
    uploaded_by: str | None = None,
) -> Path:
    if kind not in KINDS:
        raise ValueError(f"Unsupported project file kind: {kind}")
    expected_suffix = ".ifc" if kind in DISCIPLINES else ".csv"
    if Path(original_filename).suffix.lower() != expected_suffix:
        raise ValueError(f"{kind} requires a {expected_suffix} file")
    project = storage.get_project(db_path, project_id)
    root = Path(project["root_path"]).resolve()
    target = (
        model_slot_path(root, kind, CDEState.WIP)
        if kind in DISCIPLINES
        else root / FILENAMES[kind]
    )
    overwritten = target.is_file()
    _write_upload(target, source)
    storage.upsert_project_file(
        db_path,
        project_id,
        kind,
        target,
        original_filename,
        uploaded_by=uploaded_by,
    )
    if kind in DISCIPLINES:
        storage.upsert_model_slot(
            db_path,
            project_id,
            kind,
            CDEState.WIP,
            target,
            original_filename,
            created_by_role=uploaded_by,
        )
        _audit_slot_action(
            db_path,
            project_id,
            uploaded_by,
            "upload_wip",
            kind,
            None,
            CDEState.WIP,
            overwritten,
        )
    return target


def migrate_legacy_ifc_slots(db_path: Path) -> None:
    """Copy legacy root IFCs into stable WIP paths without deleting legacy files."""
    for project in storage.list_projects(db_path):
        project_id = int(project["id"])
        root = Path(project["root_path"]).resolve()
        for discipline in DISCIPLINES:
            slot = storage.get_model_slot(
                db_path, project_id, discipline, CDEState.WIP
            )
            if slot is None:
                continue
            source = Path(slot["path"]).resolve()
            target = model_slot_path(root, discipline, CDEState.WIP)
            if source == target or not source.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                shutil.copy2(source, target)
            target.with_suffix(".frag").unlink(missing_ok=True)
            storage.update_model_slot_path(
                db_path, project_id, discipline, CDEState.WIP, target
            )
            storage.update_project_file_path(db_path, project_id, discipline, target)


def _copy_slot(
    db_path: Path,
    project_id: int,
    discipline: str,
    source_state: CDEState,
    target_state: CDEState,
    created_by_role: str | None,
) -> tuple[dict, bool]:
    source_slot = storage.get_model_slot(
        db_path, project_id, discipline, source_state
    )
    if source_slot is None:
        raise FileNotFoundError(
            f"{discipline} {source_state.value} model is not available"
        )
    source_path = Path(source_slot["path"]).resolve()
    project = storage.get_project(db_path, project_id)
    root = Path(project["root_path"]).resolve()
    if not source_path.is_relative_to(root) or not source_path.is_file():
        raise ValueError("Stored IFC path is invalid")
    target_path = model_slot_path(root, discipline, target_state)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    overwritten = storage.get_model_slot(
        db_path, project_id, discipline, target_state
    ) is not None
    temporary = target_path.with_suffix(target_path.suffix + ".copy")
    shutil.copy2(source_path, temporary)
    temporary.replace(target_path)
    target_path.with_suffix(".frag").unlink(missing_ok=True)
    record = storage.upsert_model_slot(
        db_path,
        project_id,
        discipline,
        target_state,
        target_path,
        source_slot["original_filename"],
        created_by_role=created_by_role,
        source_state=source_state,
    )
    return record, overwritten


def submit_shared(
    db_path: Path,
    project_id: int,
    discipline: str,
    created_by_role: str | None,
) -> dict:
    before = {
        item_discipline
        for item_discipline, state in storage.model_slots(db_path, project_id)
        if state == CDEState.SHARED.value
    }
    record, overwritten = _copy_slot(
        db_path,
        project_id,
        discipline,
        CDEState.WIP,
        CDEState.SHARED,
        created_by_role,
    )
    after = sorted(before | {discipline})
    if overwritten:
        title = f"{discipline} Shared model updated"
        notification_type = "shared_updated"
    elif len(after) == 2:
        title = f"Shared federation ready: {' + '.join(after)}"
        notification_type = "shared_ready"
    elif len(after) == 3:
        title = f"Shared federation updated: {' + '.join(after)}"
        notification_type = "shared_ready"
    else:
        title = ""
        notification_type = ""
    if title:
        storage.create_notification(
            db_path,
            project_id,
            "PM-BIM",
            notification_type,
            title,
            {"discipline": discipline, "disciplines": after},
            source_id=f"slot:{record['id']}:{record['generation']}",
        )
    _audit_slot_action(
        db_path,
        project_id,
        created_by_role,
        "submit_shared",
        discipline,
        CDEState.WIP,
        CDEState.SHARED,
        overwritten,
    )
    return record


def publish_model(
    db_path: Path,
    project_id: int,
    discipline: str,
    created_by_role: str | None,
) -> dict:
    existing = storage.get_model_slot(
        db_path, project_id, discipline, CDEState.PUBLISHED
    )
    if existing is not None:
        _copy_slot(
            db_path,
            project_id,
            discipline,
            CDEState.PUBLISHED,
            CDEState.ARCHIVED,
            created_by_role,
        )
    record, overwritten = _copy_slot(
        db_path,
        project_id,
        discipline,
        CDEState.SHARED,
        CDEState.PUBLISHED,
        created_by_role,
    )
    _audit_slot_action(
        db_path,
        project_id,
        created_by_role,
        "publish_model",
        discipline,
        CDEState.SHARED,
        CDEState.PUBLISHED,
        overwritten,
    )
    return record


def archive_model(
    db_path: Path,
    project_id: int,
    discipline: str,
    created_by_role: str | None,
) -> dict:
    record, overwritten = _copy_slot(
        db_path,
        project_id,
        discipline,
        CDEState.PUBLISHED,
        CDEState.ARCHIVED,
        created_by_role,
    )
    _audit_slot_action(
        db_path,
        project_id,
        created_by_role,
        "archive_model",
        discipline,
        CDEState.PUBLISHED,
        CDEState.ARCHIVED,
        overwritten,
    )
    return record


def resolve_model_slot(
    db_path: Path,
    project_id: int,
    discipline: str,
    cde_state: CDEState,
) -> tuple[str, Path, dict]:
    discipline = discipline.strip().upper()
    if discipline not in DISCIPLINES:
        raise ValueError("discipline must be ARC, STR, or MEP")
    record = storage.get_model_slot(db_path, project_id, discipline, cde_state)
    if record is None and cde_state is CDEState.WIP:
        legacy = storage.project_files(db_path, project_id).get(discipline)
        if legacy is not None:
            record = storage.upsert_model_slot(
                db_path,
                project_id,
                discipline,
                CDEState.WIP,
                Path(legacy["path"]),
                legacy["original_filename"],
                created_by_role=legacy.get("uploaded_by"),
            )
    if record is None:
        raise FileNotFoundError(
            f"{discipline} {cde_state.value} model is not available"
        )
    path = Path(record["path"]).resolve()
    root = Path(storage.get_project(db_path, project_id)["root_path"]).resolve()
    if (
        not path.is_relative_to(root)
        or path.name != FILENAMES[discipline]
        or not path.is_file()
    ):
        raise ValueError("Stored IFC path is invalid")
    return discipline, path, record


def resolve_ifc(
    db_path: Path,
    project_id: int,
    file_name: str,
    cde_state: CDEState = CDEState.WIP,
) -> tuple[str, Path]:
    normalized = Path(file_name).name.upper()
    aliases = {"ARC.IFC": "ARC", "STR.IFC": "STR", "MEP.IFC": "MEP"}
    discipline = aliases.get(normalized)
    if discipline is None:
        raise ValueError("file_name must be ARC.ifc, STR.ifc, or MEP.ifc")
    kind, path, _ = resolve_model_slot(db_path, project_id, discipline, cde_state)
    return kind, path


def resolve_csv(
    db_path: Path,
    project_id: int,
    file_name: str,
) -> tuple[str, Path]:
    normalized = Path(file_name).name.lower()
    aliases = {"cost.csv": "COST", "schedule.csv": "SCHEDULE"}
    kind = aliases.get(normalized)
    if kind is None:
        raise ValueError("file_name must be Cost.csv or Schedule.csv")
    file_record = storage.project_files(db_path, project_id).get(kind)
    if file_record is None:
        raise FileNotFoundError(f"{FILENAMES[kind]} has not been uploaded")
    path = Path(file_record["path"]).resolve()
    root = Path(storage.get_project(db_path, project_id)["root_path"]).resolve()
    if not path.is_relative_to(root) or path.name != FILENAMES[kind] or not path.is_file():
        raise ValueError("Stored CSV path is invalid")
    return kind, path
