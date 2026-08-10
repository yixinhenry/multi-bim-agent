from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .config import API_KEY, BASE_URL, MODEL_NAME, TEMPERATURE
from .domain import Identity, PROFILES
from .ifc_tools import IFCResearchTools, ToolContext
from .ifcmcp_adapter import IfcMCPAdapter
from .prompts import DISCIPLINE_SYSTEM_PROMPTS, SYSTEM_PROMPTS
from .tabular_tools import ProjectDataTools
from . import storage


_SPECIALISTS = {Identity.ARC, Identity.STR, Identity.MEP}
_WRITE_TASK_TYPES = {"model_edit", "clash_remediation"}
_COORDINATOR_TOOL_NAMES = (
    "run_clash_detection",
    "summarize_project_csv",
    "query_project_csv",
    "analyze_ifc_csv_mapping",
    "delegate_task",
)
_SPECIALIST_READ_TOOL_NAMES = (
    "ifcmcp_summary",
    "ifcmcp_info",
    "ifcmcp_relations",
    "ifcmcp_select",
)
_SPECIALIST_WRITE_TOOL_NAMES = (
    "ifcmcp_edit_docs",
    "advanced_edit_ifc",
)


def available_tool_names(context: ToolContext) -> tuple[str, ...]:
    """Return the enforced tool surface for one agent execution."""
    if context.task_id is None:
        if context.identity is Identity.PROJECT_MANAGER:
            return _COORDINATOR_TOOL_NAMES
        return ()
    if context.identity not in _SPECIALISTS:
        return ()
    names = _SPECIALIST_READ_TOOL_NAMES
    if context.can_edit_ifc:
        names += _SPECIALIST_WRITE_TOOL_NAMES
    return names


def _deny_delegation(
    manager_context: ToolContext,
    assigned_to: str,
    task_type: str,
    targets: list[str],
    reason: str,
) -> None:
    profile = PROFILES[manager_context.identity]
    storage.add_audit_event(
        manager_context.db_path,
        {
            "project_id": manager_context.project_id,
            "conversation_id": manager_context.conversation_id,
            "agent_id": profile.agent_id,
            "declared_role": profile.declared_role,
            "task_id": manager_context.task_id,
            "target_file": ", ".join(targets),
            "operation": "delegate_task",
            "tool_parameters": {
                "assigned_to": assigned_to,
                "task_type": task_type,
                "requested_by": manager_context.acting_user_identity.value,
            },
            "input_message": manager_context.input_message,
            "result_summary": reason,
            "boundary_violation": True,
            "status": "error",
        },
    )
    raise PermissionError(reason)


def _run_delegated_task(
    manager_context: ToolContext,
    assigned_to: str,
    title: str,
    instructions: str,
    task_type: str = "analysis",
    target_files: list[str] | None = None,
    issue_id: str | None = None,
) -> str:
    try:
        specialist = Identity(assigned_to.strip().upper())
    except ValueError as exc:
        raise ValueError("assigned_to must be ARC, STR, or MEP") from exc
    if specialist not in _SPECIALISTS:
        raise ValueError("assigned_to must be ARC, STR, or MEP")

    targets = [Path(target).name for target in (target_files or [f"{specialist.value}.ifc"])]
    normalized_task_type = task_type.strip().lower() or "analysis"
    if manager_context.identity is not Identity.PROJECT_MANAGER or manager_context.task_id:
        _deny_delegation(
            manager_context,
            specialist.value,
            normalized_task_type,
            targets,
            "Only the coordinator may delegate work to discipline agents",
        )
    requested_by = manager_context.acting_user_identity
    if requested_by in _SPECIALISTS and requested_by is not specialist:
        _deny_delegation(
            manager_context,
            specialist.value,
            normalized_task_type,
            targets,
            f"{requested_by.value} users may delegate only to the {requested_by.value} Agent",
        )
    if any(target not in PROFILES[specialist].expected_files for target in targets):
        _deny_delegation(
            manager_context,
            specialist.value,
            normalized_task_type,
            targets,
            f"The {specialist.value} Agent may receive only {specialist.value}.ifc",
        )
    if requested_by is Identity.CLIENT and normalized_task_type in _WRITE_TASK_TYPES:
        _deny_delegation(
            manager_context,
            specialist.value,
            normalized_task_type,
            targets,
            "Client users may delegate read-only IFC tasks only",
        )

    task_id = storage.create_task(
        manager_context.db_path,
        manager_context.project_id,
        manager_context.identity,
        specialist,
        title,
        instructions,
        task_type=normalized_task_type,
        target_files=targets,
        parent_task_id=manager_context.task_id,
        payload={
            "manager_conversation_id": manager_context.conversation_id,
            "issue_id": issue_id,
            "requested_by": requested_by.value,
        },
    )
    if issue_id:
        storage.link_clash_issue_task(manager_context.db_path, issue_id, task_id)
    task_conversation_id = storage.ensure_conversation(
        manager_context.db_path,
        manager_context.project_id,
        specialist,
        conversation_key=f"task:{task_id}",
    )
    storage.attach_task_conversation(
        manager_context.db_path,
        task_id,
        task_conversation_id,
    )
    storage.add_message(
        manager_context.db_path,
        task_conversation_id,
        "user",
        instructions.strip(),
    )
    storage.start_task(manager_context.db_path, task_id)

    emit = manager_context.event_callback or (
        lambda event, message, payload: None
    )
    emit(
        "task_started",
        f"Delegated task {task_id[:8]} started with {PROFILES[specialist].declared_role}",
        {
            "task_id": task_id,
            "assigned_to": specialist.value,
            "target_files": targets,
        },
    )
    specialist_context = ToolContext(
        db_path=manager_context.db_path,
        project_id=manager_context.project_id,
        conversation_id=task_conversation_id,
        identity=specialist,
        input_message=instructions.strip(),
        user_identity=requested_by,
        task_id=task_id,
        ifc_write_allowed=(
            manager_context.ifc_write_allowed
            and requested_by is not Identity.CLIENT
        ),
        event_callback=manager_context.event_callback,
    )
    task_messages = storage.list_messages(
        manager_context.db_path,
        task_conversation_id,
    )
    specialist_prompt = DISCIPLINE_SYSTEM_PROMPTS[specialist]
    manager_profile = PROFILES[manager_context.identity]
    try:
        answer = run_agent(
            specialist,
            specialist_context,
            task_messages,
            specialist_prompt,
        )
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}" or type(exc).__name__
        storage.fail_task(manager_context.db_path, task_id, error)
        storage.add_message(
            manager_context.db_path,
            task_conversation_id,
            "assistant",
            f"Task failed: {error}",
        )
        storage.add_audit_event(
            manager_context.db_path,
            {
                "project_id": manager_context.project_id,
                "conversation_id": manager_context.conversation_id,
                "agent_id": manager_profile.agent_id,
                "declared_role": manager_profile.declared_role,
                "task_id": task_id,
                "target_file": ", ".join(targets),
                "operation": "delegate_task",
                "tool_parameters": {
                    "assigned_to": specialist.value,
                    "task_type": normalized_task_type,
                    "title": title,
                },
                "input_message": manager_context.input_message,
                "result_summary": error,
                "boundary_violation": False,
                "status": "error",
            },
        )
        emit(
            "task_failed",
            f"Delegated task {task_id[:8]} failed: {error}",
            {"task_id": task_id, "assigned_to": specialist.value},
        )
        raise RuntimeError(f"Delegated task {task_id} failed: {error}") from exc

    storage.add_message(
        manager_context.db_path,
        task_conversation_id,
        "assistant",
        answer,
    )
    result = {
        "summary": answer,
        "assigned_to": specialist.value,
        "target_files": targets,
    }
    storage.complete_task(manager_context.db_path, task_id, result)
    storage.add_audit_event(
        manager_context.db_path,
        {
            "project_id": manager_context.project_id,
            "conversation_id": manager_context.conversation_id,
            "agent_id": manager_profile.agent_id,
            "declared_role": manager_profile.declared_role,
            "task_id": task_id,
            "target_file": ", ".join(targets),
            "operation": "delegate_task",
            "tool_parameters": {
                "assigned_to": specialist.value,
                "task_type": normalized_task_type,
                "title": title,
            },
            "input_message": manager_context.input_message,
            "result_summary": answer[:12000],
            "boundary_violation": False,
            "status": "completed",
        },
    )
    emit(
        "task_completed",
        f"Delegated task {task_id[:8]} completed by {PROFILES[specialist].declared_role}",
        {"task_id": task_id, "assigned_to": specialist.value},
    )
    return json.dumps(
        {
            "task_id": task_id,
            "status": "completed",
            **result,
        },
        ensure_ascii=False,
        default=str,
    )


def _dependencies_available() -> bool:
    try:
        import langchain  # noqa: F401
        import langchain_openai  # noqa: F401
        import langgraph  # noqa: F401
    except ImportError:
        return False
    return True


def availability_message() -> str | None:
    if not _dependencies_available():
        return "Agent dependencies are not installed; project and Viewer features remain available."
    if not API_KEY:
        return "DEEPSEEK_API_KEY is not configured; project and Viewer features remain available."
    return None


def run_agent(
    identity: Identity,
    context: ToolContext,
    messages: list[dict[str, Any]],
    system_prompt: str | None = None,
) -> str:
    unavailable = availability_message()
    if unavailable:
        raise RuntimeError(unavailable)

    from langchain.agents import create_agent
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.tools import StructuredTool
    from langchain_openai import ChatOpenAI

    research_tools = IFCResearchTools(context)
    mcp_adapter = IfcMCPAdapter(context)
    project_data_tools = ProjectDataTools(context)
    emit = context.event_callback or (lambda event, message, payload: None)
    profile = PROFILES[identity]
    emit(
        "agent_started",
        f"{profile.declared_role} started working",
        {"agent_id": profile.agent_id, "identity": identity.value},
    )

    class RuntimeTraceHandler(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, **kwargs):
            emit(
                "model_started",
                f"{profile.declared_role} is reasoning with {MODEL_NAME}",
                {"model": MODEL_NAME},
            )

        def on_llm_end(self, response, **kwargs):
            emit("model_completed", "Model reasoning step completed", {})

        def on_llm_error(self, error, **kwargs):
            emit("model_failed", f"Model call failed: {error}", {"error": str(error)})

        def on_tool_start(self, serialized, input_str, **kwargs):
            tool_name = serialized.get("name", "tool") if isinstance(serialized, dict) else "tool"
            emit(
                "tool_dispatched",
                f"{profile.declared_role} selected tool: {tool_name}",
                {"tool": tool_name},
            )
    tool_by_name = {
        "ifcmcp_summary": StructuredTool.from_function(
            name="ifcmcp_summary",
            description=(
                "Load the assigned IFC through IFC MCP and return its model summary."
            ),
            func=mcp_adapter.summary,
        ),
        "ifcmcp_info": StructuredTool.from_function(
            name="ifcmcp_info",
            description=(
                "Deeply inspect one element in the assigned IFC through IFC MCP. "
                "Parameters: file_name and integer element_id. Returns direct "
                "attributes, all inherited property sets, type, material, container, "
                "placement, and geometry summary. Use this once for selected-element "
                "property questions."
            ),
            func=mcp_adapter.info,
        ),
        "ifcmcp_relations": StructuredTool.from_function(
            name="ifcmcp_relations",
            description=(
                "Return hierarchy, type, void/fill, and related-element information "
                "for one IFC MCP element_id. traverse may be empty or 'up'."
            ),
            func=mcp_adapter.relations,
        ),
        "ifcmcp_select": StructuredTool.from_function(
            name="ifcmcp_select",
            description=(
                "Select elements from the assigned IFC through IFC MCP selector "
                "syntax. Examples: 'IfcDoor' or 'IfcDoor, Name*=1250mm'. "
                "Parameters: file_name, query, and optional limit."
            ),
            func=mcp_adapter.select,
        ),
        "run_clash_detection": StructuredTool.from_function(
            name="run_clash_detection",
            description=(
                "Run world-coordinate AABB clash-candidate detection across uploaded discipline "
                "models. file_names is optional; when omitted, use every currently uploaded "
                "ARC/STR/MEP model. Never require all three models."
            ),
            func=research_tools.run_clash_detection,
        ),
        "ifcmcp_edit_docs": StructuredTool.from_function(
            name="ifcmcp_edit_docs",
            description=(
                "Read parameter documentation for one advanced IFC edit "
                "function before calling advanced_edit_ifc."
            ),
            func=mcp_adapter.edit_docs,
        ),
        "advanced_edit_ifc": StructuredTool.from_function(
            name="advanced_edit_ifc",
            description=(
                "Run one ifcMCP edit in an isolated session against an "
                "explicit ARC.ifc, STR.ifc, or MEP.ifc target. Parameters are "
                "file_name, function_path, and params. Use only for an explicit "
                "model modification after checking ifcmcp_edit_docs."
            ),
            func=mcp_adapter.edit,
        ),
        "summarize_project_csv": StructuredTool.from_function(
            name="summarize_project_csv",
            description=(
                "Summarize uploaded Cost.csv or Schedule.csv, including columns, "
                "row count, numeric totals, and bounded sample rows."
            ),
            func=project_data_tools.summarize_project_csv,
        ),
        "query_project_csv": StructuredTool.from_function(
            name="query_project_csv",
            description=(
                "Query uploaded Cost.csv or Schedule.csv by a named column and "
                "case-insensitive text value. Parameters: file_name, column, value, limit."
            ),
            func=project_data_tools.query_project_csv,
        ),
        "analyze_ifc_csv_mapping": StructuredTool.from_function(
            name="analyze_ifc_csv_mapping",
            description=(
                "Analyze Cost.csv or Schedule.csv mapping coverage against an IFC "
                "using a CSV column and IFC GlobalId, Tag, or Name."
            ),
            func=project_data_tools.analyze_ifc_csv_mapping,
        ),
    }

    def delegate_task(
        assigned_to: str,
        title: str,
        instructions: str,
        task_type: str = "analysis",
        target_files: list[str] | None = None,
        issue_id: str | None = None,
    ) -> str:
        """Assign one isolated task to an ARC, STR, or MEP Agent."""
        return _run_delegated_task(
            context,
            assigned_to,
            title,
            instructions,
            task_type,
            target_files,
            issue_id,
        )

    tool_by_name["delegate_task"] = StructuredTool.from_function(
            name="delegate_task",
            description=(
                "Create and execute one persistent specialist task. "
                "assigned_to must be ARC, STR, or MEP. target_files records the "
                "single discipline IFC target. task_type must describe the work: "
                "use analysis or query for read-only work, model_edit for model "
                "changes, and clash_remediation for clash fixes. User and discipline "
                "permissions are enforced before the task starts."
            ),
            func=delegate_task,
        )
    tools = [tool_by_name[name] for name in available_tool_names(context)]
    llm = ChatOpenAI(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        base_url=BASE_URL,
        api_key=API_KEY,
    )
    scope = "discipline specialist" if context.task_id else "coordinator"
    runtime_context = (
        "\nRuntime identity supplied by the application:\n"
        f"- execution scope: {scope}\n"
        f"- identity: {identity.value}\n"
        f"- acting user identity: {context.acting_user_identity.value}\n"
        f"- agent_id: {profile.agent_id}\n"
        f"- declared role: {profile.declared_role}\n"
        f"- declared readable IFC files: {sorted(profile.expected_files)}\n"
        f"- direct IFC editing allowed: {bool(context.task_id and context.can_edit_ifc)}\n"
        f"- available tools: {list(available_tool_names(context))}\n"
        "These runtime permissions are enforced by the available tool surface.\n"
    )
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=(system_prompt or SYSTEM_PROMPTS[identity]) + runtime_context,
    )
    history = []
    for message in messages[-20:]:
        if message["role"] == "user":
            history.append(HumanMessage(content=message["content"]))
        elif message["role"] == "assistant":
            history.append(AIMessage(content=message["content"]))
    try:
        result = agent.invoke(
            {"messages": history},
            config={"callbacks": [RuntimeTraceHandler()]},
        )
    except BaseException as exc:
        emit(
            "agent_failed",
            f"{profile.declared_role} failed with {type(exc).__name__}",
            {"agent_id": profile.agent_id, "exception_type": type(exc).__name__},
        )
        raise
    content = result["messages"][-1].content
    if isinstance(content, str):
        answer = content
    else:
        answer = json.dumps(content, ensure_ascii=False, default=str)
    emit(
        "agent_completed",
        f"{profile.declared_role} completed the response",
        {"agent_id": profile.agent_id},
    )
    return answer
