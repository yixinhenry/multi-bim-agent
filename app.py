from __future__ import annotations

import queue
import threading
import time
from itertools import combinations
from pathlib import Path

import streamlit as st

from bim_multi import projects, storage
from bim_multi.agent import availability_message, run_agent
from bim_multi.config import DB_PATH, MODEL_NAME, PROJECTS_DIR
from bim_multi.diagnostics import diagnostic_markdown, exception_diagnostic
from bim_multi.domain import (
    PROFILES,
    ROLES_BY_IDENTITY,
    ROLE_PROFILES,
    Identity,
    ProjectRole,
    can_view_schedule,
    visible_context_roles,
)
from bim_multi.ifc_tools import ToolContext
from bim_multi.prompts import SYSTEM_PROMPTS, system_prompt_for_role
from bim_multi.schedule import load_schedule
from bim_multi.viewer_server import start_viewer_server


IDENTITY_ORDER = [
    Identity.CLIENT,
    Identity.PROJECT_MANAGER,
    Identity.ARC,
    Identity.STR,
    Identity.MEP,
]


@st.cache_resource
def viewer_url(db_path: str) -> str:
    return start_viewer_server(Path(db_path))


def inject_css() -> None:
    st.markdown(
        """
        <style>
        header[data-testid="stHeader"] {
            display: block !important;
            height: 0 !important;
            background: transparent !important;
            pointer-events: none !important;
            overflow: visible !important;
        }
        [data-testid="stToolbar"] {
            display: flex !important;
            pointer-events: none !important;
            background: transparent !important;
            overflow: visible !important;
        }
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stExpandSidebarButton"] {
            display: flex !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            position: fixed !important;
            top: .7rem !important;
            left: .45rem !important;
            z-index: 1000000 !important;
            width: 2rem !important;
            height: 2rem !important;
            align-items: center !important;
            justify-content: center !important;
            border: 1px solid #d8e0e8 !important;
            border-radius: .45rem !important;
            background: #ffffff !important;
            box-shadow: 0 2px 8px rgba(15, 23, 42, .12) !important;
        }
        [data-testid="stSidebarCollapseButton"] {
            display: flex !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
        }
        [data-testid="stBaseButton-header"],
        [data-testid="stMainMenuButton"],
        [data-testid="stStatusWidget"],
        [data-testid="stDecoration"] {
            display: none !important;
        }
        .block-container { max-width: 100%; padding: .7rem 1rem 1rem; }
        .app-title { font-size: 1.1rem; font-weight: 700; }
        .muted { color: #64748b; font-size: .8rem; }
        .identity-card {
            border: 1px solid #dbe3ec; border-radius: 10px; padding: .7rem;
            background: #fff; margin-bottom: .5rem;
        }
        .viewer-column-marker,
        .chat-column-marker,
        .clash-panel-marker { display: none; }
        [data-testid="stColumn"]:has(.viewer-column-marker) {
            position: sticky;
            top: .7rem;
            align-self: flex-start;
            z-index: 2;
        }
        [data-testid="stColumn"]:has(.chat-column-marker) {
            margin-top: -1rem;
        }
        [data-testid="stExpander"]:has(.clash-panel-marker)
        [data-testid="stExpanderDetails"] {
            max-height: 55vh;
            overflow-y: auto;
            padding-right: .35rem;
        }
        iframe { border: 1px solid #dbe3ec !important; border-radius: 12px; }
        [data-testid="stChatMessage"] { padding: .7rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_project_files(project_id: int) -> None:
    file_records = storage.project_files(DB_PATH, project_id)
    st.markdown("#### Project files")
    for kind, label, file_type in [
        ("ARC", "ARC.ifc", ["ifc"]),
        ("STR", "STR.ifc", ["ifc"]),
        ("MEP", "MEP.ifc", ["ifc"]),
        ("COST", "Cost.csv (optional)", ["csv"]),
        ("SCHEDULE", "Schedule.csv (optional)", ["csv"]),
    ]:
        record = file_records.get(kind)
        if record:
            st.caption(f"✓ {label} — {record['original_filename']}")
        else:
            st.caption(f"○ {label} — not uploaded")
        upload = st.file_uploader(
            f"Upload or replace {label}",
            type=file_type,
            key=f"upload-{project_id}-{kind}",
            label_visibility="collapsed",
        )
        if upload is not None and st.button(
            f"Save {label}",
            key=f"save-{project_id}-{kind}",
            use_container_width=True,
        ):
            try:
                projects.save_upload(
                    DB_PATH, project_id, kind, upload.name, upload
                )
            except Exception as exc:
                st.error(f"Unable to save {label}: {exc}")
            else:
                st.success(f"{label} uploaded.")
                st.rerun()


def render_project_menu() -> int | None:
    available = storage.list_projects(DB_PATH)
    ids = [item["id"] for item in available]
    names = {item["id"]: item["name"] for item in available}
    selector_id = st.session_state.get("project-selector")
    current_id = (
        selector_id
        if selector_id in ids
        else st.session_state.get("project_id")
    )
    if current_id not in ids:
        current_id = ids[0] if ids else None
    if st.session_state.get("project-selector") not in ids:
        st.session_state["project-selector"] = current_id

    arrow_space, menu_column, _, status_column = st.columns([.35, 1.05, 6.8, 1.8])
    with menu_column:
        with st.popover("Project", use_container_width=True):
            st.markdown("### Project management")
            if available:
                selected_id = st.selectbox(
                    "Open project",
                    ids,
                    key="project-selector",
                    format_func=lambda item: f"{names[item]} · P{item:03d}",
                )
                st.session_state.project_id = selected_id
                st.caption(
                    "Switching projects also switches all identity conversations, "
                    "model files, Viewer state, and system prompts."
                )
                st.divider()
                render_project_files(selected_id)
                st.divider()
            else:
                selected_id = None
                st.info("No projects yet. Create the first project below.")

            st.markdown("#### New project")
            with st.form("create-project-form", clear_on_submit=True):
                name = st.text_input("Project name", key="new-project-name")
                submitted = st.form_submit_button(
                    "Create and open project",
                    use_container_width=True,
                )
            if submitted:
                if not name.strip():
                    st.error("Enter a project name.")
                else:
                    new_project_id = projects.create(
                        DB_PATH, PROJECTS_DIR, name.strip()
                    )
                    st.session_state.project_id = new_project_id
                    st.session_state.pop("project-selector", None)
                    st.rerun()
    if current_id is None:
        status_column.caption("No active project")
    else:
        model_count = len(
            {"ARC", "STR", "MEP"} & set(storage.project_files(DB_PATH, current_id))
        )
        status_column.caption(f"Status: Ready · {model_count}/3 models")
    return st.session_state.get("project_id")


def render_sidebar_schedule(project_id: int, project_role: ProjectRole) -> None:
    if not can_view_schedule(project_role):
        return
    with st.sidebar.container(border=True):
        st.markdown("**Project schedule**")
        schedule_record = storage.project_files(DB_PATH, project_id).get("SCHEDULE")
        if schedule_record is None:
            st.caption("Schedule.csv has not been uploaded.")
            return
        try:
            summary = load_schedule(Path(schedule_record["path"]))
        except (OSError, ValueError) as exc:
            st.error(f"Unable to display Schedule.csv: {exc}")
            return

        st.progress(
            summary.overall_progress / 100,
            text=f"Overall progress · {summary.overall_progress:.0f}%",
        )
        st.caption(
            f"{summary.planned_start.isoformat()} → "
            f"{summary.planned_finish.isoformat()} · "
            f"{summary.completed_tasks}/{len(summary.tasks)} tasks completed"
        )
        with st.expander(f"Schedule tasks ({len(summary.tasks)})"):
            for task in summary.tasks:
                st.markdown(f"**{task.name}**")
                detail = " · ".join(
                    value
                    for value in (task.discipline, task.status)
                    if value
                )
                st.progress(
                    task.progress / 100,
                    text=f"{detail} · {task.progress:g}%",
                )
                st.caption(
                    f"{task.planned_start.isoformat()} → "
                    f"{task.planned_finish.isoformat()}"
                )


def render_sidebar(project_id: int | None) -> ProjectRole:
    st.sidebar.markdown('<div class="app-title">BIM Multi-Agent</div>', unsafe_allow_html=True)
    st.sidebar.caption(f"Model: {MODEL_NAME}")
    if project_id is None:
        st.sidebar.info("Create a project from the menu in the top-left corner.")
        return ProjectRole.CL_REP
    project = storage.get_project(DB_PATH, project_id)
    st.sidebar.caption(f"Project: {project['name']} · P{project_id:03d}")

    selected_value = st.session_state.get("_active_project_role", ProjectRole.CL_REP.value)
    try:
        selected_role = ProjectRole(selected_value)
    except ValueError:
        selected_role = ProjectRole.CL_REP

    render_sidebar_schedule(project_id, selected_role)
    st.sidebar.divider()
    st.sidebar.caption("Current identity")
    for group_identity in IDENTITY_ORDER:
        group_roles = ROLES_BY_IDENTITY[group_identity]
        with st.sidebar.expander(
            PROFILES[group_identity].label,
            expanded=ROLE_PROFILES[selected_role].identity is group_identity,
        ):
            for role in group_roles:
                role_profile = ROLE_PROFILES[role]
                if st.button(
                    f"{role_profile.label} · {role.value}",
                    key=f"select-role-{project_id}-{role.value}",
                    type="primary" if role is selected_role else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["_active_project_role"] = role.value
                    st.rerun()

    previous_identity = st.session_state.get("_active_identity")
    identity = ROLE_PROFILES[selected_role].identity
    if previous_identity is not None and previous_identity != identity.value:
        st.session_state.pop("viewer_clash", None)
    st.session_state["_active_identity"] = identity.value
    role_profile = ROLE_PROFILES[selected_role]
    st.sidebar.markdown(
        f'<div class="identity-card"><strong>{role_profile.label}</strong>'
        f'<div class="muted">Role: {selected_role.value}</div>'
        f'<div class="muted">Agent: {PROFILES[Identity.PROJECT_MANAGER].declared_role}</div>'
        f'<div class="muted">Conversation: {project_id}:{selected_role.value}</div>'
        f'<div class="muted">{role_profile.responsibility}</div></div>',
        unsafe_allow_html=True,
    )
    return selected_role


def model_choices(project_id: int, identity: Identity) -> list[tuple[str, ...]]:
    available = [
        kind
        for kind in ("ARC", "STR", "MEP")
        if kind in storage.project_files(DB_PATH, project_id)
    ]
    choices = [
        choice
        for size in range(1, len(available) + 1)
        for choice in combinations(available, size)
    ]
    if identity in {Identity.ARC, Identity.STR, Identity.MEP}:
        choices = [choice for choice in choices if identity.value in choice]
    return choices


def model_query(project_id: int, disciplines: tuple[str, ...]) -> tuple[str, str]:
    files = storage.project_files(DB_PATH, project_id)
    versions = []
    for kind in disciplines:
        path = Path(files[kind]["path"])
        versions.append(f"{kind}:{path.stat().st_mtime_ns}:{path.stat().st_size}")
    return ",".join(disciplines), "|".join(versions)


def render_viewer(project_id: int, identity: Identity) -> None:
    choices = model_choices(project_id, identity)
    if not choices:
        st.info("No permitted IFC model combination is available. Upload this identity's model first.")
        return
    selector_key = f"viewer-models-{project_id}-{identity.value}"
    override = st.session_state.pop("viewer_model_override", None)
    if (
        override
        and override["project_id"] == project_id
        and override["identity"] == identity.value
        and tuple(override["models"]) in choices
    ):
        st.session_state[selector_key] = tuple(override["models"])
    if st.session_state.get(selector_key) not in choices:
        st.session_state[selector_key] = choices[-1]
    selected = st.selectbox(
        "Models",
        choices,
        format_func=lambda choice: (
            choice[0] if len(choice) == 1 else f"Federated: {' + '.join(choice)}"
        ),
        key=selector_key,
    )
    kinds, version = model_query(project_id, selected)
    url = viewer_url(str(DB_PATH))
    clash = st.session_state.get("viewer_clash")
    clash_query = ""
    if (
        clash
        and clash["project_id"] == project_id
        and clash.get("identity") == identity.value
    ):
        clash_query = (
            f"&clash_a={clash['model_a']}:{clash['global_id_a']}"
            f"&clash_b={clash['model_b']}:{clash['global_id_b']}"
        )
    st.iframe(
        f"{url}/?project_id={project_id}&identity={identity.value}"
        f"&models={kinds}&v={version}{clash_query}",
        height=720,
    )

def render_task_panel(project_id: int) -> None:
    tasks = storage.list_tasks(DB_PATH, project_id, limit=20)
    with st.expander(f"Delegated tasks ({len(tasks)})"):
        if not tasks:
            st.caption("No delegated tasks yet.")
            return
        icons = {
            "pending": "[ ]",
            "running": "[>]",
            "completed": "[x]",
            "failed": "[!]",
        }
        for task in tasks:
            icon = icons.get(task["status"], "[-]")
            st.markdown(
                f"**{icon} {task['title']}** - {task['assigned_to']} "
                f"- `{task['id'][:8]}`"
            )
            targets = ", ".join(task["target_files"]) or "No target file"
            st.caption(
                f"{task['status']} - {task['task_type']} - {targets} "
                f"- updated {task['updated_at']}"
            )
            if task.get("error_text"):
                st.error(task["error_text"])
            elif task.get("result") and task["result"].get("summary"):
                summary = str(task["result"]["summary"])
                st.caption(summary[:700] + ("..." if len(summary) > 700 else ""))
            st.divider()


def render_clash_issue_panel(project_id: int, identity: Identity) -> None:
    issues = storage.list_clash_issues(DB_PATH, project_id, limit=50)
    active = [issue for issue in issues if issue["status"] != "resolved"]
    with st.expander(f"Clash issues ({len(active)} active / {len(issues)} total)"):
        st.markdown(
            '<span class="clash-panel-marker"></span>',
            unsafe_allow_html=True,
        )
        if not issues:
            st.caption("No persisted clash issues yet.")
            return
        for issue in issues:
            assignee = issue.get("assigned_to") or "Unassigned"
            st.markdown(
                f"**[{issue['status']}] {issue['title']}** "
                f"- {assignee} - `{issue['id'][:8]}`"
            )
            st.caption(
                f"{issue['model_a']}-{issue['model_b']} "
                f"- last seen {issue['last_seen_at']}"
            )
            global_id_a = issue["element_a"].get("global_id")
            global_id_b = issue["element_b"].get("global_id")
            if global_id_a and global_id_b and st.button(
                "Highlight in Viewer",
                key=f"highlight-clash-{issue['id']}",
            ):
                st.session_state.viewer_clash = {
                    "project_id": project_id,
                    "identity": identity.value,
                    "model_a": issue["model_a"],
                    "global_id_a": global_id_a,
                    "model_b": issue["model_b"],
                    "global_id_b": global_id_b,
                }
                required = {issue["model_a"], issue["model_b"]}
                if identity in {Identity.ARC, Identity.STR, Identity.MEP}:
                    required.add(identity.value)
                st.session_state.viewer_model_override = {
                    "project_id": project_id,
                    "identity": identity.value,
                    "models": [
                        kind for kind in ("ARC", "STR", "MEP") if kind in required
                    ],
                }
                st.rerun()
            st.divider()


def render_chat(project_id: int, project_role: ProjectRole) -> None:
    role_profile = ROLE_PROFILES[project_role]
    identity = role_profile.identity
    agent_profile = PROFILES[Identity.PROJECT_MANAGER]
    visible_roles = visible_context_roles(project_role)
    context_role = project_role
    st.subheader(role_profile.label)
    st.caption(f"{agent_profile.declared_role} · Isolated role memory")
    if len(visible_roles) > 1:
        context_role = st.selectbox(
            "Conversation context",
            visible_roles,
            format_func=lambda role: f"{ROLE_PROFILES[role].label} · {role.value}",
            key=f"context-role-{project_id}-{project_role.value}",
        )
    conversation_id = storage.ensure_role_conversation(
        DB_PATH,
        project_id,
        context_role,
    )
    read_only_context = context_role is not project_role
    render_task_panel(project_id)
    render_clash_issue_panel(project_id, identity)
    with st.container(height=500, border=True):
        messages = storage.list_role_context_messages(
            DB_PATH,
            project_id,
            project_role,
            context_role,
        )
        if not messages:
            st.caption("No messages yet.")
        for message in messages:
            if message["role"] in {"user", "assistant"}:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
    warning = availability_message()
    if warning:
        st.caption(warning)
    prompt = None
    if read_only_context:
        st.info(
            f"Read-only {context_role.value} context. Return to "
            f"{project_role.value} to continue your own conversation."
        )
    else:
        prompt = st.chat_input(
            "Enter a natural-language task",
            key=f"chat-{project_id}-{project_role.value}",
        )
    if prompt:
        storage.add_message(DB_PATH, conversation_id, "user", prompt)
        messages = storage.list_messages(DB_PATH, conversation_id)
        selection = storage.get_selection(DB_PATH, project_id, identity)
        if selection:
            messages[-1] = {
                **messages[-1],
                "content": messages[-1]["content"]
                + "\n\nViewer selection supplied by the application: "
                f"{selection['model_kind']}.ifc, #{selection['step_id']}, "
                f"{selection.get('ifc_type')}, GlobalId={selection.get('global_id')}, "
                f"Name={selection.get('name')}.",
            }
        base_system_prompt = storage.get_system_prompt(
            DB_PATH, project_id, identity, SYSTEM_PROMPTS[identity]
        )
        system_prompt = system_prompt_for_role(base_system_prompt, project_role)
        with st.status(
            f"{agent_profile.declared_role} is working",
            expanded=True,
        ) as runtime_status:
            runtime_status.write(
                f"**Agent:** {agent_profile.declared_role} (`{agent_profile.agent_id}`)"
            )

            event_queue: queue.Queue[tuple[str, str, dict]] = queue.Queue()
            result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

            def enqueue_runtime_event(
                event: str,
                message: str,
                payload: dict,
            ) -> None:
                event_queue.put((event, message, payload))

            def render_runtime_event(event: str, message: str) -> None:
                icon = {
                    "agent_started": "▶️",
                    "task_started": "??",
                    "task_completed": "?",
                    "task_failed": "?",
                    "model_started": "🧠",
                    "model_completed": "✓",
                    "model_failed": "⚠️",
                    "tool_dispatched": "↪️",
                    "tool_started": "🛠️",
                    "tool_completed": "✅",
                    "tool_failed": "❌",
                    "agent_completed": "🏁",
                    "agent_failed": "❌",
                }.get(event, "•")
                runtime_status.write(f"{icon} {message}")

            context = ToolContext(
                db_path=DB_PATH,
                project_id=project_id,
                conversation_id=conversation_id,
                identity=Identity.PROJECT_MANAGER,
                input_message=prompt,
                user_identity=identity,
                event_callback=enqueue_runtime_event,
            )

            def run_agent_in_worker() -> None:
                try:
                    result_queue.put(
                        (
                            "completed",
                            run_agent(
                                Identity.PROJECT_MANAGER,
                                context,
                                messages,
                                system_prompt,
                            ),
                        )
                    )
                except BaseException as exc:
                    result_queue.put(("error", exc))

            worker = threading.Thread(
                target=run_agent_in_worker,
                name=f"project-manager-agent-{project_id}-{identity.value}",
                daemon=True,
            )
            worker.start()
            while worker.is_alive() or not event_queue.empty():
                try:
                    event, message, _ = event_queue.get(timeout=0.1)
                except queue.Empty:
                    time.sleep(0.05)
                    continue
                render_runtime_event(event, message)
            worker.join()
            while not event_queue.empty():
                event, message, _ = event_queue.get_nowait()
                render_runtime_event(event, message)

            outcome, value = result_queue.get()
            if outcome == "completed":
                answer = str(value)
                runtime_status.update(
                    label=f"{agent_profile.declared_role} completed",
                    state="complete",
                    expanded=False,
                )
            else:
                exc = value
                assert isinstance(exc, BaseException)
                diagnostic = exception_diagnostic(exc)
                diagnostic_text = diagnostic_markdown(diagnostic)
                answer = f"## Run failed\n\n{diagnostic_text}"
                runtime_status.write(
                    "❌ Run failed — "
                    f"`{diagnostic['exception_type']}` "
                    f"(diagnostic `{diagnostic['diagnostic_id']}`)"
                )
                print(
                    "[BIM Multi-Agent failure]\n"
                    + diagnostic_text
                    + "\n",
                    flush=True,
                )
                storage.add_audit_event(
                    DB_PATH,
                    {
                        "project_id": project_id,
                        "conversation_id": conversation_id,
                        "agent_id": agent_profile.agent_id,
                        "declared_role": agent_profile.declared_role,
                        "target_file": None,
                        "operation": "agent_run",
                        "tool_parameters": {
                            "diagnostic_id": diagnostic["diagnostic_id"],
                            "exception_type": diagnostic["exception_type"],
                            "repr": diagnostic["repr"],
                            "cause_chain": diagnostic["cause_chain"],
                            "traceback": diagnostic["traceback"],
                        },
                        "input_message": prompt,
                        "result_summary": diagnostic["message"],
                        "boundary_violation": False,
                        "status": "error",
                    },
                )
                runtime_status.update(
                    label=(
                        f"{agent_profile.declared_role} failed "
                        f"({diagnostic['diagnostic_id']})"
                    ),
                    state="error",
                    expanded=True,
                )
        storage.add_message(DB_PATH, conversation_id, "assistant", answer)
        st.rerun()

    with st.expander("System prompt for this project and identity"):
        current_prompt = storage.get_system_prompt(
            DB_PATH, project_id, identity, SYSTEM_PROMPTS[identity]
        )
        edited_prompt = st.text_area(
            "System prompt",
            value=current_prompt,
            height=260,
            key=f"system-prompt-{project_id}-{identity.value}",
        )
        if st.button(
            "Save system prompt",
            key=f"save-system-prompt-{project_id}-{identity.value}",
            use_container_width=True,
        ):
            if not edited_prompt.strip():
                st.error("The system prompt cannot be empty.")
            else:
                storage.set_system_prompt(
                    DB_PATH, project_id, identity, edited_prompt.strip()
                )
                st.success("System prompt saved for this project and identity.")
        st.markdown("**Applied detailed role policy**")
        st.caption(f"{project_role.value}: {role_profile.prompt_policy}")


def main() -> None:
    st.set_page_config(
        page_title="BIM Multi-Agent",
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    storage.init_db(DB_PATH)
    project_id = render_project_menu()
    project_role = render_sidebar(project_id)
    if project_id is None:
        st.title("BIM Multi-Agent IFC Collaboration Platform")
        st.info("Create the first project from the menu in the top-left corner.")
        return
    identity = ROLE_PROFILES[project_role].identity
    project = storage.get_project(DB_PATH, project_id)
    top_left, top_middle = st.columns([2, 2])
    top_left.markdown(f"### {project['name']}")
    top_middle.caption(
        f"Current role: {ROLE_PROFILES[project_role].label} · {project_role.value}"
    )
    viewer_column, chat_column = st.columns([2.15, 1], gap="medium")
    with viewer_column:
        st.markdown(
            '<span class="viewer-column-marker"></span>',
            unsafe_allow_html=True,
        )
        render_viewer(project_id, identity)
    with chat_column:
        st.markdown(
            '<span class="chat-column-marker"></span>',
            unsafe_allow_html=True,
        )
        render_chat(project_id, project_role)


if __name__ == "__main__":
    main()
