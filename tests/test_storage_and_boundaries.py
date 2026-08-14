from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from bim_multi import projects, storage
from bim_multi.domain import (
    ROLE_PROFILES,
    Identity,
    ProjectRole,
    can_view_schedule,
    expected_access,
    visible_context_roles,
)
from bim_multi.ifc_tools import IFCResearchTools, ToolContext


def test_identity_boundaries_are_declared_but_not_global() -> None:
    assert expected_access(Identity.ARC, "ARC.ifc")
    assert not expected_access(Identity.ARC, "MEP.ifc")
    assert expected_access(Identity.CLIENT, "ARC.ifc", "query_ifc")
    assert expected_access(Identity.PROJECT_MANAGER, "MEP.ifc", "read_ifc")
    assert not expected_access(Identity.CLIENT, "ARC.ifc", "edit_ifc")
    assert not expected_access(Identity.PROJECT_MANAGER, "MEP.ifc", "edit_ifc")


def test_project_files_and_conversations_are_isolated(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    project_dir = tmp_path / "projects"
    storage.init_db(db_path)
    project_id = projects.create(db_path, project_dir, "Test")
    projects.save_upload(
        db_path, project_id, "ARC", "architecture.ifc", BytesIO(b"ISO-10303-21;")
    )
    assert Path(storage.project_files(db_path, project_id)["ARC"]["path"]).name == "ARC.ifc"

    arc_conversation = storage.ensure_conversation(db_path, project_id, Identity.ARC)
    mep_conversation = storage.ensure_conversation(db_path, project_id, Identity.MEP)
    assert arc_conversation != mep_conversation
    storage.add_message(db_path, arc_conversation, "user", "ARC only")
    assert len(storage.list_messages(db_path, arc_conversation)) == 1
    assert storage.list_messages(db_path, mep_conversation) == []


def test_project_file_version_metadata_increments_on_replacement(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    project_dir = tmp_path / "projects"
    storage.init_db(db_path)
    project_id = projects.create(db_path, project_dir, "Versioned")

    projects.save_upload(
        db_path,
        project_id,
        "ARC",
        "architecture-v1.ifc",
        BytesIO(b"ISO-10303-21;v1"),
        uploaded_by="ARC-MOD",
    )
    first = storage.project_files(db_path, project_id)["ARC"]
    assert first["revision_number"] == 1
    assert first["uploaded_by"] == "ARC-MOD"
    assert first["approved_by"] is None

    projects.save_upload(
        db_path,
        project_id,
        "ARC",
        "architecture-v2.ifc",
        BytesIO(b"ISO-10303-21;v2"),
        uploaded_by="ARC-LEAD",
    )
    second = storage.project_files(db_path, project_id)["ARC"]
    assert second["revision_number"] == 2
    assert second["uploaded_by"] == "ARC-LEAD"
    assert second["approved_by"] is None


def test_detailed_roles_and_lead_context_visibility() -> None:
    assert len(ROLE_PROFILES) == 14
    assert visible_context_roles(ProjectRole.ARC_CHK) == (ProjectRole.ARC_CHK,)
    assert visible_context_roles(ProjectRole.PM_MGR) == (ProjectRole.PM_MGR,)
    assert visible_context_roles(ProjectRole.CL_APP) == (ProjectRole.CL_APP,)
    assert visible_context_roles(ProjectRole.ARC_LEAD) == (
        ProjectRole.ARC_MOD,
        ProjectRole.ARC_CHK,
        ProjectRole.ARC_LEAD,
    )
    assert visible_context_roles(ProjectRole.STR_LEAD) == (
        ProjectRole.STR_MOD,
        ProjectRole.STR_CHK,
        ProjectRole.STR_LEAD,
    )
    assert visible_context_roles(ProjectRole.MEP_LEAD) == (
        ProjectRole.MEP_MOD,
        ProjectRole.MEP_CHK,
        ProjectRole.MEP_LEAD,
    )


def test_schedule_visibility_matches_p05_roles() -> None:
    visible = {role for role in ProjectRole if can_view_schedule(role)}
    assert visible == {
        ProjectRole.CL_REP,
        ProjectRole.CL_APP,
        ProjectRole.PM_BIM,
        ProjectRole.PM_CTL,
        ProjectRole.PM_MGR,
        ProjectRole.ARC_LEAD,
        ProjectRole.STR_LEAD,
        ProjectRole.MEP_LEAD,
    }


def test_role_memories_are_isolated_and_only_discipline_leads_can_read_group(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    project_id = storage.create_project(db_path, "P", tmp_path / "P")
    arc_mod = storage.ensure_role_conversation(
        db_path,
        project_id,
        ProjectRole.ARC_MOD,
    )
    arc_checker = storage.ensure_role_conversation(
        db_path,
        project_id,
        ProjectRole.ARC_CHK,
    )
    assert arc_mod != arc_checker
    storage.add_message(db_path, arc_mod, "user", "ARC modeler memory")
    storage.add_message(db_path, arc_checker, "user", "ARC checker memory")

    lead_view = storage.list_role_context_messages(
        db_path,
        project_id,
        ProjectRole.ARC_LEAD,
        ProjectRole.ARC_MOD,
    )
    assert [message["content"] for message in lead_view] == ["ARC modeler memory"]

    with pytest.raises(PermissionError, match="cannot view"):
        storage.list_role_context_messages(
            db_path,
            project_id,
            ProjectRole.ARC_CHK,
            ProjectRole.ARC_MOD,
        )
    with pytest.raises(PermissionError, match="cannot view"):
        storage.list_role_context_messages(
            db_path,
            project_id,
            ProjectRole.ARC_LEAD,
            ProjectRole.MEP_MOD,
        )


def test_ifc_tool_blocks_and_audits_cross_discipline_access(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    project_id = storage.create_project(db_path, "P", tmp_path / "P")
    conversation_id = storage.ensure_conversation(db_path, project_id, Identity.ARC)
    context = ToolContext(
        db_path=db_path,
        project_id=project_id,
        conversation_id=conversation_id,
        identity=Identity.ARC,
        input_message="Read MEP.ifc.",
        task_id="task-1",
    )

    with pytest.raises(PermissionError, match="not allowed to run read_ifc"):
        IFCResearchTools(context).read_ifc("MEP.ifc")

    events = storage.list_audit_events(db_path, project_id, conversation_id)
    assert events[0]["boundary_violation"] == 1
    assert events[0]["target_file"] == "MEP.ifc"
    assert events[0]["status"] == "error"


def test_system_prompt_is_isolated_by_project_and_identity(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = storage.create_project(db_path, "First", first_root)
    second = storage.create_project(db_path, "Second", second_root)
    storage.set_system_prompt(db_path, first, Identity.ARC, "first ARC prompt")
    assert storage.get_system_prompt(db_path, first, Identity.ARC, "default") == "first ARC prompt"
    assert storage.get_system_prompt(db_path, first, Identity.MEP, "default") == "default"
    assert storage.get_system_prompt(db_path, second, Identity.ARC, "default") == "default"


def test_multiple_user_messages_remain_visible_in_order(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "Project", root)
    conversation_id = storage.ensure_conversation(db_path, project_id, Identity.STR)
    storage.add_message(db_path, conversation_id, "user", "First request")
    storage.add_message(db_path, conversation_id, "assistant", "First response")
    storage.add_message(db_path, conversation_id, "user", "Second request")
    messages = storage.list_messages(db_path, conversation_id)
    assert [item["content"] for item in messages] == [
        "First request",
        "First response",
        "Second request",
    ]

def test_task_lifecycle_and_task_conversation_are_persistent(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "Project", root)

    task_id = storage.create_task(
        db_path,
        project_id,
        Identity.PROJECT_MANAGER,
        Identity.ARC,
        "Inspect selected wall",
        "Query the selected wall and report its IFC identifiers.",
        target_files=["ARC.ifc"],
    )
    task_conversation = storage.ensure_conversation(
        db_path,
        project_id,
        Identity.ARC,
        conversation_key=f"task:{task_id}",
    )
    main_conversation = storage.ensure_conversation(
        db_path,
        project_id,
        Identity.ARC,
    )
    storage.attach_task_conversation(db_path, task_id, task_conversation)
    storage.add_message(db_path, task_conversation, "user", "Task-only context")
    storage.start_task(db_path, task_id)
    storage.complete_task(
        db_path,
        task_id,
        {"summary": "Wall inspected", "target_files": ["ARC.ifc"]},
    )

    task = storage.get_task(db_path, task_id)
    assert task["status"] == "completed"
    assert task["conversation_id"] == task_conversation
    assert task["target_files"] == ["ARC.ifc"]
    assert task["result"]["summary"] == "Wall inspected"
    assert storage.list_messages(db_path, main_conversation) == []
    assert storage.list_messages(db_path, task_conversation)[0]["content"] == "Task-only context"


def test_cross_discipline_task_target_is_recorded_without_blocking(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "Project", root)

    task_id = storage.create_task(
        db_path,
        project_id,
        Identity.PROJECT_MANAGER,
        Identity.ARC,
        "Research boundary case",
        "Attempt a cross-discipline target and audit downstream tool use.",
        target_files=["MEP.ifc"],
    )

    task = storage.get_task(db_path, task_id)
    assert task["assigned_to"] == "ARC"
    assert task["target_files"] == ["MEP.ifc"]


def test_failed_task_records_error(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "Project", root)
    task_id = storage.create_task(
        db_path,
        project_id,
        Identity.PROJECT_MANAGER,
        Identity.MEP,
        "Inspect services",
        "Inspect the uploaded MEP model.",
        target_files=["MEP.ifc"],
    )
    storage.start_task(db_path, task_id)
    storage.fail_task(db_path, task_id, "MEP.ifc has not been uploaded")

    task = storage.get_task(db_path, task_id)
    assert task["status"] == "failed"
    assert task["error_text"] == "MEP.ifc has not been uploaded"

def test_clash_issue_deduplicates_and_links_resolution_task(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "Project", root)
    clash = {
        "pair": "ARC-MEP",
        "a": {
            "step_id": 10,
            "ifc_type": "IfcWall",
            "global_id": "ARC-GUID",
            "name": "Wall",
        },
        "b": {
            "step_id": 20,
            "ifc_type": "IfcDuctSegment",
            "global_id": "MEP-GUID",
            "name": "Duct",
        },
        "distance": 0.0,
    }

    first_ids = storage.upsert_clash_issues(db_path, project_id, [clash])
    clash["distance"] = -0.01
    second_ids = storage.upsert_clash_issues(db_path, project_id, [clash])
    assert first_ids == second_ids
    assert len(storage.list_clash_issues(db_path, project_id)) == 1

    task_id = storage.create_task(
        db_path,
        project_id,
        Identity.PROJECT_MANAGER,
        Identity.MEP,
        "Resolve duct clash",
        "Move the MEP element and recheck the clash.",
        task_type="clash_remediation",
        target_files=["MEP.ifc"],
        payload={"issue_id": first_ids[0]},
    )
    storage.link_clash_issue_task(db_path, first_ids[0], task_id)
    assigned = storage.list_clash_issues(db_path, project_id)[0]
    assert assigned["status"] == "assigned"
    assert assigned["assigned_to"] == "MEP"
    assert assigned["resolution_task_id"] == task_id

    storage.resolve_clash_issue(db_path, first_ids[0])
    resolved = storage.list_clash_issues(
        db_path,
        project_id,
        status="resolved",
    )
    assert [issue["id"] for issue in resolved] == first_ids
