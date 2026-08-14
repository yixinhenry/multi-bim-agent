from __future__ import annotations

import re
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from . import storage


KINDS = ("ARC", "STR", "MEP", "COST", "SCHEDULE")
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
    expected_suffix = ".ifc" if kind in {"ARC", "STR", "MEP"} else ".csv"
    if Path(original_filename).suffix.lower() != expected_suffix:
        raise ValueError(f"{kind} requires a {expected_suffix} file")
    project = storage.get_project(db_path, project_id)
    root = Path(project["root_path"]).resolve()
    target = root / FILENAMES[kind]
    payload = source.read()
    if not payload:
        raise ValueError("Uploaded file is empty")
    temporary = target.with_suffix(target.suffix + ".upload")
    temporary.write_bytes(payload)
    temporary.replace(target)
    target.with_suffix(".frag").unlink(missing_ok=True)
    storage.upsert_project_file(
        db_path,
        project_id,
        kind,
        target,
        original_filename,
        uploaded_by=uploaded_by,
    )
    return target


def resolve_ifc(
    db_path: Path, project_id: int, file_name: str
) -> tuple[str, Path]:
    normalized = Path(file_name).name.upper()
    aliases = {"ARC.IFC": "ARC", "STR.IFC": "STR", "MEP.IFC": "MEP"}
    kind = aliases.get(normalized)
    if kind is None:
        raise ValueError("file_name must be ARC.ifc, STR.ifc, or MEP.ifc")
    file_record = storage.project_files(db_path, project_id).get(kind)
    if file_record is None:
        raise FileNotFoundError(f"{kind}.ifc has not been uploaded")
    path = Path(file_record["path"]).resolve()
    root = Path(storage.get_project(db_path, project_id)["root_path"]).resolve()
    if not path.is_relative_to(root) or path.name != FILENAMES[kind] or not path.is_file():
        raise ValueError("Stored IFC path is invalid")
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
