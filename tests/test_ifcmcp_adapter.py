from __future__ import annotations

import json
from pathlib import Path

import pytest

from bim_multi import storage
from bim_multi.domain import Identity
from bim_multi.ifc_tools import ToolContext
from bim_multi.ifcmcp_adapter import IfcMCPAdapter


class FakeSession:
    def __init__(self) -> None:
        self.payload = b""

    def ifc_load(self, path: str) -> str:
        self.payload = Path(path).read_bytes()
        return f"Loaded {Path(path).name}"

    def ifc_edit(self, function_path: str, params: dict) -> dict:
        self.payload += b"\nEDITED"
        return {
            "ok": True,
            "result": {"function_path": function_path, "params": params},
        }

    def ifc_save(self, path: str) -> str:
        Path(path).write_bytes(self.payload)
        return f"Saved {Path(path).name}"

    def ifc_docs(self, function_path: str) -> dict:
        return {"function_path": function_path}

    def ifc_summary(self) -> dict:
        return {"schema": "IFC4", "entity_count": 10}

    def ifc_info(self, element_id: int) -> dict:
        return {
            "id": element_id,
            "type": "IfcDoor",
            "attributes": {"OverallHeight": 2.01, "OverallWidth": 1.25},
            "property_sets": {"Pset_DoorCommon": {"FireRating": "60 min"}},
        }

    def ifc_relations(self, element_id: int, traverse: str = "") -> dict:
        return {"id": element_id, "traverse": traverse, "elements": []}

    def ifc_select(self, query: str) -> list[dict]:
        return [
            {"id": index, "type": "IfcDoor", "name": f"Door {index}"}
            for index in range(1, 4)
        ]


class FailingSession(FakeSession):
    def ifc_edit(self, function_path: str, params: dict) -> dict:
        return {"ok": False, "error": "simulated edit failure"}


def make_context(
    tmp_path: Path,
    identity: Identity = Identity.ARC,
    kind: str = "ARC",
) -> tuple[ToolContext, Path]:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "Project", root)
    path = root / f"{kind}.ifc"
    path.write_bytes(b"ISO-10303-21;")
    storage.upsert_project_file(db_path, project_id, kind, path, f"{kind}.ifc")
    conversation_id = storage.ensure_conversation(db_path, project_id, identity)
    return (
        ToolContext(
            db_path=db_path,
            project_id=project_id,
            conversation_id=conversation_id,
            identity=identity,
            input_message="Apply an explicit advanced edit.",
            task_id="task-1",
        ),
        path,
    )


def test_ifcmcp_edit_uses_isolated_sessions_and_atomic_target(tmp_path: Path) -> None:
    context, path = make_context(tmp_path)
    path.with_suffix(".frag").write_bytes(b"cache")
    sessions = []

    def factory() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    result = IfcMCPAdapter(context, session_factory=factory).edit(
        "ARC.ifc",
        "attribute.edit_attributes",
        {"product": 42, "attributes": {"Name": "Updated"}},
    )

    assert "one session per edit call" in result
    assert path.read_bytes().endswith(b"EDITED")
    assert not path.with_suffix(".frag").exists()
    assert len(sessions) == 2
    events = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )
    assert events[0]["operation"] == "ifcmcp_edit"
    assert events[0]["status"] == "completed"
    assert events[0]["boundary_violation"] == 0


def test_ifcmcp_query_loads_assigned_model_and_returns_deep_info(
    tmp_path: Path,
) -> None:
    context, _ = make_context(tmp_path)
    result = json.loads(
        IfcMCPAdapter(context, session_factory=FakeSession).info(
            "ARC.ifc",
            252,
        )
    )

    assert result["id"] == 252
    assert result["attributes"]["OverallWidth"] == 1.25
    assert result["property_sets"]["Pset_DoorCommon"]["FireRating"] == "60 min"
    events = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )
    assert events[0]["operation"] == "ifcmcp_info"
    assert events[0]["status"] == "completed"


def test_ifcmcp_select_bounds_results(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path)
    result = json.loads(
        IfcMCPAdapter(context, session_factory=FakeSession).select(
            "ARC.ifc",
            "IfcDoor",
            limit=2,
        )
    )

    assert result["matched_count"] == 3
    assert result["returned_count"] == 2
    assert result["truncated"] is True
    assert len(result["elements"]) == 2


def test_ifcmcp_query_blocks_cross_discipline_model(tmp_path: Path) -> None:
    context, _ = make_context(tmp_path, identity=Identity.ARC, kind="MEP")

    with pytest.raises(PermissionError, match="not allowed to query MEP.ifc"):
        IfcMCPAdapter(context, session_factory=FakeSession).info("MEP.ifc", 7)

    events = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )
    assert events[0]["operation"] == "ifcmcp_info"
    assert events[0]["boundary_violation"] == 1


def test_ifcmcp_failure_preserves_original_file(tmp_path: Path) -> None:
    context, path = make_context(tmp_path)
    original = path.read_bytes()
    adapter = IfcMCPAdapter(context, session_factory=FailingSession)

    with pytest.raises(RuntimeError, match="simulated edit failure"):
        adapter.edit(
            "ARC.ifc",
            "attribute.edit_attributes",
            {"product": 42, "attributes": {"Name": "Updated"}},
        )

    assert path.read_bytes() == original
    events = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )
    assert events[0]["status"] == "error"


def test_ifcmcp_cross_boundary_edit_is_blocked_and_audited(tmp_path: Path) -> None:
    context, path = make_context(tmp_path, identity=Identity.ARC, kind="MEP")
    adapter = IfcMCPAdapter(context, session_factory=FakeSession)

    with pytest.raises(PermissionError, match="not allowed to modify MEP.ifc"):
        adapter.edit(
            "MEP.ifc",
            "attribute.edit_attributes",
            {"product": 7, "attributes": {"Name": "Research case"}},
        )

    assert not path.read_bytes().endswith(b"EDITED")
    events = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )
    assert events[0]["boundary_violation"] == 1
    assert events[0]["status"] == "error"


def test_client_cannot_run_ifcmcp_edit(tmp_path: Path) -> None:
    context, path = make_context(tmp_path)
    context = ToolContext(
        db_path=context.db_path,
        project_id=context.project_id,
        conversation_id=context.conversation_id,
        identity=Identity.ARC,
        input_message=context.input_message,
        user_identity=Identity.CLIENT,
        task_id="task-1",
        ifc_write_allowed=False,
    )

    with pytest.raises(PermissionError, match="current user"):
        IfcMCPAdapter(context, session_factory=FakeSession).edit(
            "ARC.ifc",
            "attribute.edit_attributes",
            {"product": 7, "attributes": {"Name": "Blocked"}},
        )

    assert not path.read_bytes().endswith(b"EDITED")


def test_ifcmcp_does_not_apply_a_function_permission_list(tmp_path: Path) -> None:
    context, path = make_context(tmp_path)
    adapter = IfcMCPAdapter(context, session_factory=FakeSession)

    result = adapter.edit("ARC.ifc", "project.create_file", {})

    assert "project.create_file" in result
    assert path.read_bytes().endswith(b"EDITED")
