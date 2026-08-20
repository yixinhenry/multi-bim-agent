from __future__ import annotations

from pathlib import Path

import pytest

from bim_multi import agent, storage
from bim_multi.domain import Identity
from bim_multi.ifc_tools import ToolContext


def make_manager_context(
    tmp_path: Path,
    user_identity: Identity = Identity.PROJECT_MANAGER,
) -> ToolContext:
    db_path = tmp_path / "app.db"
    storage.init_db(db_path)
    root = tmp_path / "project"
    root.mkdir()
    project_id = storage.create_project(db_path, "Project", root)
    conversation_id = storage.ensure_conversation(
        db_path,
        project_id,
        Identity.PROJECT_MANAGER,
    )
    return ToolContext(
        db_path=db_path,
        project_id=project_id,
        conversation_id=conversation_id,
        identity=Identity.PROJECT_MANAGER,
        input_message="Ask ARC to inspect the model.",
        user_identity=user_identity,
    )


def test_manager_delegation_persists_specialist_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = make_manager_context(tmp_path)

    def fake_run_agent(identity, task_context, messages, system_prompt=None):
        assert identity is Identity.ARC
        assert task_context.task_id
        assert task_context.conversation_id != context.conversation_id
        assert [message["content"] for message in messages] == [
            "Inspect the architectural model."
        ]
        return "ARC inspection completed."

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)
    result = agent._run_delegated_task(
        context,
        "ARC",
        "Inspect architecture",
        "Inspect the architectural model.",
        target_files=["ARC.ifc"],
    )

    assert "ARC inspection completed." in result
    tasks = storage.list_tasks(context.db_path, context.project_id)
    assert len(tasks) == 1
    assert tasks[0]["status"] == "completed"
    assert tasks[0]["assigned_to"] == "ARC"
    task_messages = storage.list_messages(
        context.db_path,
        tasks[0]["conversation_id"],
    )
    assert [message["role"] for message in task_messages] == ["user", "assistant"]
    assert task_messages[-1]["content"] == "ARC inspection completed."


def test_manager_delegation_records_specialist_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = make_manager_context(tmp_path)

    def failing_run_agent(identity, task_context, messages, system_prompt=None):
        raise RuntimeError("specialist failed")

    monkeypatch.setattr(agent, "run_agent", failing_run_agent)
    with pytest.raises(RuntimeError, match="specialist failed"):
        agent._run_delegated_task(
            context,
            "MEP",
            "Inspect services",
            "Inspect the services model.",
            target_files=["MEP.ifc"],
        )

    task = storage.list_tasks(context.db_path, context.project_id)[0]
    assert task["status"] == "failed"
    assert "specialist failed" in task["error_text"]
    events = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )
    assert events[0]["operation"] == "delegate_task"
    assert events[0]["status"] == "error"

def test_specialist_cannot_delegate_another_task(
    tmp_path: Path,
) -> None:
    manager_context = make_manager_context(tmp_path)
    arc_conversation = storage.ensure_conversation(
        manager_context.db_path,
        manager_context.project_id,
        Identity.ARC,
    )
    arc_context = ToolContext(
        db_path=manager_context.db_path,
        project_id=manager_context.project_id,
        conversation_id=arc_conversation,
        identity=Identity.ARC,
        input_message="Ask MEP to inspect ARC.ifc as a boundary experiment.",
    )

    with pytest.raises(PermissionError, match="Only the coordinator"):
        agent._run_delegated_task(
            arc_context,
            "MEP",
            "Boundary experiment",
            "Inspect the target and report the result.",
            target_files=["ARC.ifc"],
        )

    assert storage.list_tasks(
        arc_context.db_path,
        arc_context.project_id,
    ) == []
    events = storage.list_audit_events(
        arc_context.db_path,
        arc_context.project_id,
        arc_context.conversation_id,
    )
    assert events[0]["operation"] == "delegate_task"
    assert events[0]["boundary_violation"] == 1
    assert events[0]["status"] == "error"


def test_coordinator_and_specialist_tool_surfaces_are_separate(
    tmp_path: Path,
) -> None:
    coordinator = make_manager_context(tmp_path)
    assert set(agent.available_tool_names(coordinator)) == {
        "run_clash_detection",
        "assign_clash_issues",
        "summarize_project_csv",
        "query_project_csv",
        "analyze_ifc_csv_mapping",
        "delegate_task",
    }
    assert {
        "read_ifc",
        "query_ifc",
        "edit_ifc",
        "ifcmcp_info",
        "advanced_edit_ifc",
    }.isdisjoint(agent.available_tool_names(coordinator))

    specialist = ToolContext(
        db_path=coordinator.db_path,
        project_id=coordinator.project_id,
        conversation_id=coordinator.conversation_id,
        identity=Identity.ARC,
        input_message="Inspect ARC.ifc.",
        user_identity=Identity.PROJECT_MANAGER,
        task_id="task-1",
    )
    assert set(agent.available_tool_names(specialist)) == {
        "ifcmcp_summary",
        "ifcmcp_info",
        "ifcmcp_relations",
        "ifcmcp_select",
        "ifcmcp_edit_docs",
        "advanced_edit_ifc",
    }


def test_discipline_user_cannot_delegate_to_another_discipline(
    tmp_path: Path,
) -> None:
    context = make_manager_context(tmp_path, Identity.ARC)

    with pytest.raises(PermissionError, match="ARC users may delegate only"):
        agent._run_delegated_task(
            context,
            "MEP",
            "Inspect services",
            "Inspect MEP.ifc.",
            target_files=["MEP.ifc"],
        )

    assert storage.list_tasks(context.db_path, context.project_id) == []
    event = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )[0]
    assert event["boundary_violation"] == 1
    assert event["tool_parameters"]["requested_by"] == "ARC"


def test_client_delegation_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = make_manager_context(tmp_path, Identity.CLIENT)

    def fake_run_agent(identity, task_context, messages, system_prompt=None):
        assert identity is Identity.STR
        assert task_context.acting_user_identity is Identity.CLIENT
        assert not task_context.can_edit_ifc
        assert set(agent.available_tool_names(task_context)) == {
            "ifcmcp_summary",
            "ifcmcp_info",
            "ifcmcp_relations",
            "ifcmcp_select",
        }
        return "Read-only inspection completed."

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)
    result = agent._run_delegated_task(
        context,
        "STR",
        "Inspect structure",
        "Read STR.ifc and report its contents.",
        task_type="query",
        target_files=["STR.ifc"],
    )
    assert "Read-only inspection completed." in result

    with pytest.raises(PermissionError, match="read-only IFC tasks"):
        agent._run_delegated_task(
            context,
            "STR",
            "Change structure",
            "Modify STR.ifc.",
            task_type="model_edit",
            target_files=["STR.ifc"],
        )
