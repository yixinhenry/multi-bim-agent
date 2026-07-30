from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from bim_multi import projects, storage
from bim_multi.domain import Identity, expected_access


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


def test_audit_records_boundary_violation(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    project_id = storage.create_project(db_path, "P", tmp_path / "P")
    conversation_id = storage.ensure_conversation(db_path, project_id, Identity.ARC)
    storage.add_audit_event(
        db_path,
        {
            "project_id": project_id,
            "conversation_id": conversation_id,
            "agent_id": "arc-agent",
            "declared_role": "ARC Agent",
            "target_file": "MEP.ifc",
            "operation": "read_ifc",
            "tool_parameters": {},
            "boundary_violation": True,
            "status": "completed",
        },
    )
    events = storage.list_audit_events(db_path, project_id, conversation_id)
    assert events[0]["boundary_violation"] == 1
    assert events[0]["target_file"] == "MEP.ifc"


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
