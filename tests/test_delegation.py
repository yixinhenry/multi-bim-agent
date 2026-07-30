from __future__ import annotations

from pathlib import Path

import pytest

from bim_multi import agent, storage
from bim_multi.domain import Identity
from bim_multi.ifc_tools import ToolContext


def make_manager_context(tmp_path: Path) -> ToolContext:
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

def test_internal_agent_delegation_executes_and_is_audited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    def fake_run_agent(identity, task_context, messages, system_prompt=None):
        assert identity is Identity.MEP
        return "Out-of-bound delegated task executed."

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)
    result = agent._run_delegated_task(
        arc_context,
        "MEP",
        "Boundary experiment",
        "Inspect the target and report the result.",
        target_files=["ARC.ifc"],
    )

    assert "Out-of-bound delegated task executed." in result
    events = storage.list_audit_events(
        arc_context.db_path,
        arc_context.project_id,
        arc_context.conversation_id,
    )
    assert events[0]["operation"] == "delegate_task"
    assert events[0]["boundary_violation"] == 1
    assert events[0]["status"] == "completed"
