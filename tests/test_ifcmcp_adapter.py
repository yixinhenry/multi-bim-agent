from __future__ import annotations

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


def test_ifcmcp_cross_boundary_edit_executes_and_is_audited(tmp_path: Path) -> None:
    context, path = make_context(tmp_path, identity=Identity.ARC, kind="MEP")
    adapter = IfcMCPAdapter(context, session_factory=FakeSession)

    adapter.edit(
        "MEP.ifc",
        "attribute.edit_attributes",
        {"product": 7, "attributes": {"Name": "Research case"}},
    )

    assert path.read_bytes().endswith(b"EDITED")
    events = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )
    assert events[0]["boundary_violation"] == 1


def test_ifcmcp_does_not_apply_a_function_permission_list(tmp_path: Path) -> None:
    context, path = make_context(tmp_path)
    adapter = IfcMCPAdapter(context, session_factory=FakeSession)

    result = adapter.edit("ARC.ifc", "project.create_file", {})

    assert "project.create_file" in result
    assert path.read_bytes().endswith(b"EDITED")
