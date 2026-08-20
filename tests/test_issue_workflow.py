from __future__ import annotations

import json
import sys
import types
from io import BytesIO
from pathlib import Path

import pytest

from bim_multi import agent, projects, storage
from bim_multi.domain import (
    CDEState,
    ProjectRole,
    can_view_clash_issue,
    notification_recipient_key,
)
from bim_multi.ifc_tools import IFCResearchTools, ToolContext, ViewerModelSnapshot
from bim_multi.domain import Identity


def _project(tmp_path: Path) -> tuple[Path, int, int]:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "P", root)
    conversation_id = storage.ensure_role_conversation(
        db_path, project_id, ProjectRole.PM_BIM
    )
    return db_path, project_id, conversation_id


def _clash(step: int) -> dict:
    return {
        "pair": "ARC-MEP",
        "a": {"step_id": step, "global_id": f"A{step}", "ifc_type": "IfcWall"},
        "b": {"step_id": step + 100, "global_id": f"M{step}", "ifc_type": "IfcPipeSegment"},
    }


def test_issue_visibility_and_professional_assignment_notifications(tmp_path: Path) -> None:
    db_path, project_id, conversation_id = _project(tmp_path)
    issue_ids = storage.upsert_clash_issues(
        db_path, project_id, [_clash(1), _clash(2)]
    )
    context = ToolContext(
        db_path=db_path,
        project_id=project_id,
        conversation_id=conversation_id,
        identity=Identity.PROJECT_MANAGER,
        input_message="Assign these issues to MEP",
        project_role=ProjectRole.PM_BIM,
    )

    result = json.loads(
        agent.assign_clash_issue_responsibility(context, issue_ids, "MEP")
    )
    assert result["issue_count"] == 2
    assert {item["assigned_to"] for item in storage.list_clash_issues(db_path, project_id)} == {"MEP"}
    mod_notifications = storage.list_notifications(
        db_path, project_id, "MEP-MOD-GROUP"
    )
    assert len(mod_notifications) == 1
    assert len(storage.list_notifications(db_path, project_id, "MEP-CHK")) == 1
    assert notification_recipient_key(ProjectRole.MEP_MOD_HVAC) == "MEP-MOD-GROUP"
    assert notification_recipient_key(ProjectRole.MEP_MOD_BMS) == "MEP-MOD-GROUP"
    storage.mark_notification_read(db_path, project_id, mod_notifications[0]["id"])
    counts = storage.unread_notification_counts(db_path, project_id)
    assert counts.get("MEP-MOD-GROUP", 0) == 0
    assert counts["MEP-CHK"] == 1

    issue = storage.list_clash_issues(db_path, project_id)[0]
    assert can_view_clash_issue(ProjectRole.PM_BIM, "ARC", "MEP", None)
    assert can_view_clash_issue(ProjectRole.ARC_LEAD, "ARC", "MEP", None)
    assert can_view_clash_issue(ProjectRole.MEP_MOD_HVAC, "ARC", "MEP", "MEP")
    assert can_view_clash_issue(ProjectRole.MEP_CHK, "ARC", "MEP", "MEP")
    assert not can_view_clash_issue(ProjectRole.ARC_MOD_SHELL, "ARC", "MEP", "MEP")
    assert issue["status"] == "assigned"


def test_clash_detection_requires_shared_viewer_snapshot(tmp_path: Path) -> None:
    db_path, project_id, conversation_id = _project(tmp_path)
    context = ToolContext(
        db_path=db_path,
        project_id=project_id,
        conversation_id=conversation_id,
        identity=Identity.PROJECT_MANAGER,
        input_message="Run clashes",
        project_role=ProjectRole.PM_BIM,
        viewer_models=(
            ViewerModelSnapshot("ARC", CDEState.SHARED, "now", 1, 10),
        ),
    )
    with pytest.raises(ValueError, match="at least two Shared"):
        IFCResearchTools(context).run_clash_detection()

    invalid = ToolContext(
        db_path=db_path,
        project_id=project_id,
        conversation_id=conversation_id,
        identity=Identity.PROJECT_MANAGER,
        input_message="Run clashes",
        project_role=ProjectRole.PM_BIM,
        viewer_models=(
            ViewerModelSnapshot("ARC", CDEState.WIP, "now", 1, 10),
            ViewerModelSnapshot("MEP", CDEState.SHARED, "now", 1, 10),
        ),
    )
    with pytest.raises(ValueError, match="Shared Viewer combination"):
        IFCResearchTools(invalid).run_clash_detection()


def test_successful_clash_run_is_persisted_and_notified_once_per_lead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, project_id, conversation_id = _project(tmp_path)
    for discipline in ("ARC", "MEP"):
        projects.save_upload(
            db_path,
            project_id,
            discipline,
            f"{discipline}.ifc",
            BytesIO(discipline.encode()),
            uploaded_by=f"{discipline}-MOD",
        )
        projects.submit_shared(
            db_path, project_id, discipline, f"{discipline}-LEAD"
        )

    class Entity:
        Representation = object()

        def __init__(self, discipline: str) -> None:
            self.discipline = discipline
            self.GlobalId = f"{discipline}-GUID"
            self.Name = discipline

        def id(self) -> int:
            return 1 if self.discipline == "ARC" else 2

        def is_a(self, expected: str | None = None):
            value = "IfcWall" if self.discipline == "ARC" else "IfcPipeSegment"
            return value == expected if expected else value

    class Model:
        def __init__(self, path: str) -> None:
            self.entity = Entity("ARC" if "ARC.ifc" in path else "MEP")

        def by_type(self, name: str):
            return [self.entity] if name == "IfcProduct" else []

    class Settings:
        USE_WORLD_COORDS = "world"

        def set(self, *_args) -> None:
            return None

    class Iterator:
        def __init__(self, _settings, _model, _workers, include) -> None:
            entity = include[0]
            geometry = types.SimpleNamespace(verts=[0, 0, 0, 1, 1, 1])
            self.shape = types.SimpleNamespace(
                guid=entity.GlobalId,
                geometry=geometry,
            )

        def initialize(self) -> bool:
            return True

        def get(self):
            return self.shape

        def next(self) -> bool:
            return False

    geom = types.ModuleType("ifcopenshell.geom")
    geom.settings = Settings
    geom.iterator = Iterator
    ifcopenshell = types.ModuleType("ifcopenshell")
    ifcopenshell.open = Model
    ifcopenshell.geom = geom
    monkeypatch.setitem(sys.modules, "ifcopenshell", ifcopenshell)
    monkeypatch.setitem(sys.modules, "ifcopenshell.geom", geom)

    slots = storage.model_slots(db_path, project_id)
    snapshot = tuple(
        ViewerModelSnapshot(
            discipline,
            CDEState.SHARED,
            slots[(discipline, CDEState.SHARED.value)]["updated_at"],
            int(slots[(discipline, CDEState.SHARED.value)]["generation"]),
            Path(slots[(discipline, CDEState.SHARED.value)]["path"]).stat().st_size,
        )
        for discipline in ("ARC", "MEP")
    )
    context = ToolContext(
        db_path=db_path,
        project_id=project_id,
        conversation_id=conversation_id,
        identity=Identity.PROJECT_MANAGER,
        input_message="Run clashes",
        project_role=ProjectRole.PM_BIM,
        viewer_models=snapshot,
    )

    result = json.loads(IFCResearchTools(context).run_clash_detection())

    assert result["pair_counts"] == {"ARC-MEP": 1}
    assert len(storage.list_clash_runs(db_path, project_id)) == 1
    issues = storage.list_clash_issues(db_path, project_id)
    assert len(issues) == 1
    assert issues[0]["last_run_id"] == result["clash_run_id"]
    assert len(storage.list_notifications(db_path, project_id, "ARC-LEAD")) == 1
    assert len(storage.list_notifications(db_path, project_id, "MEP-LEAD")) == 1
