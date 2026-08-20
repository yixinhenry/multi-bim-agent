from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from bim_multi import projects, storage
from bim_multi.agent import availability_message, run_agent
from bim_multi.config import DB_PATH, MODEL_NAME, PROJECTS_DIR
from bim_multi.diagnostics import diagnostic_markdown, exception_diagnostic
from bim_multi.domain import (
    CHECKER_ROLES,
    DISCIPLINE_LEADS,
    MOD_ROLES,
    MOD_ROLES_BY_IDENTITY,
    PROFILES,
    ROLES_BY_IDENTITY,
    ROLE_PROFILES,
    CDEState,
    Identity,
    ProjectRole,
    can_view_schedule,
    can_view_clash_issue,
    role_discipline,
    notification_recipient_key,
    viewer_model_choices,
    visible_context_roles,
)
from bim_multi.ifc_tools import ToolContext, ViewerModelSnapshot
from bim_multi.prompts import (
    CDE_STATE_PROMPTS,
    SYSTEM_PROMPTS,
    system_prompt_for_role,
)
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
        [data-testid="stButtonGroup"] [role="radiogroup"] {
            flex-wrap: nowrap !important;
        }
        [data-testid="stButtonGroup"] button[data-variant="segmented_control"] {
            flex: 1 1 0 !important;
            min-width: 0 !important;
            padding-inline: .35rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def active_project_role() -> ProjectRole:
    try:
        return ProjectRole(
            st.session_state.get("_active_project_role", ProjectRole.CL_REP.value)
        )
    except ValueError:
        return ProjectRole.CL_REP


def render_project_files(project_id: int) -> None:
    file_records = storage.project_files(DB_PATH, project_id)
    slots = storage.model_slots(DB_PATH, project_id)
    role = active_project_role()
    discipline = role_discipline(role)
    st.markdown("#### Project files")
    if role in MOD_ROLES and discipline:
        record = slots.get((discipline, CDEState.WIP.value))
        label = f"{discipline} WIP"
        if record:
            st.caption(f"✓ {label} — {record['original_filename']}")
        else:
            st.caption(f"○ {label} — not uploaded")
        upload = st.file_uploader(
            f"Upload or replace {label}",
            type=["ifc"],
            key=f"upload-{project_id}-{discipline}-WIP",
            label_visibility="collapsed",
        )
        if upload is not None and st.button(
            f"Save {label}",
            key=f"save-{project_id}-{discipline}-WIP",
            use_container_width=True,
        ):
            try:
                projects.save_upload(
                    DB_PATH,
                    project_id,
                    discipline,
                    upload.name,
                    upload,
                    uploaded_by=role.value,
                )
            except Exception as exc:
                st.error(f"Unable to save {label}: {exc}")
            else:
                st.success(f"{label} uploaded.")
                st.rerun()
    else:
        st.caption("WIP upload is available to concrete MOD roles.")

    for kind, label, file_type in [
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
                    DB_PATH,
                    project_id,
                    kind,
                    upload.name,
                    upload,
                    uploaded_by=active_project_role().value,
                )
            except Exception as exc:
                st.error(f"Unable to save {label}: {exc}")
            else:
                st.success(f"{label} uploaded.")


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
        slots = storage.model_slots(DB_PATH, current_id)
        wip_count = sum(
            (discipline, CDEState.WIP.value) in slots
            for discipline in projects.DISCIPLINES
        )
        status_column.caption(f"Status: Ready · {wip_count}/3 WIP")
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
    unread_counts = storage.unread_notification_counts(DB_PATH, project_id)

    render_sidebar_schedule(project_id, selected_role)
    st.sidebar.divider()
    st.sidebar.caption("Current identity")
    for group_identity in IDENTITY_ORDER:
        group_roles = ROLES_BY_IDENTITY[group_identity]
        recipient_keys = {role.value for role in group_roles}
        if group_identity in {Identity.ARC, Identity.STR, Identity.MEP}:
            recipient_keys.add(f"{group_identity.value}-MOD-GROUP")
        group_unread = sum(unread_counts.get(key, 0) for key in recipient_keys)
        group_label = PROFILES[group_identity].label
        if group_unread:
            group_label += f" · 🔴 {group_unread}"
        with st.sidebar.expander(
            group_label,
            expanded=ROLE_PROFILES[selected_role].identity is group_identity,
        ):
            mod_roles = MOD_ROLES_BY_IDENTITY.get(group_identity, ())
            if mod_roles:
                mod_unread = unread_counts.get(
                    f"{group_identity.value}-MOD-GROUP", 0
                )
                st.caption(f"MOD{' · 🔴 ' + str(mod_unread) if mod_unread else ''}")
            for role in mod_roles:
                role_profile = ROLE_PROFILES[role]
                if st.button(
                    role.value,
                    key=f"select-role-{project_id}-{role.value}",
                    type="primary" if role is selected_role else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["_active_project_role"] = role.value
                    st.rerun()

            other_roles = tuple(role for role in group_roles if role not in MOD_ROLES)
            if mod_roles:
                st.caption("CHK / LEAD")
            for role in other_roles:
                role_profile = ROLE_PROFILES[role]
                role_unread = unread_counts.get(role.value, 0)
                role_label = f"{role_profile.label} · {role.value}"
                if role_unread:
                    role_label += f" · 🔴 {role_unread}"
                if st.button(
                    role_label,
                    key=f"select-role-{project_id}-{role.value}",
                    type="primary" if role is selected_role else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["_active_project_role"] = role.value
                    st.rerun()

    previous_role = st.session_state.get("_previous_project_role")
    identity = ROLE_PROFILES[selected_role].identity
    if previous_role is not None and previous_role != selected_role.value:
        st.session_state.pop("viewer_clash", None)
    st.session_state["_previous_project_role"] = selected_role.value
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


def model_choices(
    project_id: int,
    project_role: ProjectRole,
) -> list[tuple[tuple[str, CDEState], ...]]:
    available = {
        (discipline, CDEState(state))
        for discipline, state in storage.model_slots(DB_PATH, project_id)
    }
    return list(viewer_model_choices(project_role, available))


def model_query(
    project_id: int,
    choice: tuple[tuple[str, CDEState], ...],
) -> tuple[str, str]:
    slots = storage.model_slots(DB_PATH, project_id)
    tokens = []
    versions = []
    for discipline, state in choice:
        record = slots[(discipline, state.value)]
        path = Path(record["path"])
        tokens.append(f"{state.value}:{discipline}")
        versions.append(
            f"{state.value}:{discipline}:{record['updated_at']}:"
            f"{path.stat().st_size}"
        )
    return ",".join(tokens), "|".join(versions)


def _choice_label(choice: tuple[tuple[str, CDEState], ...]) -> str:
    if len(choice) == 1:
        discipline, state = choice[0]
        return f"{discipline} · {state.value}"
    return f"Federated Shared: {' + '.join(discipline for discipline, _ in choice)}"


def render_model_actions(project_id: int, project_role: ProjectRole) -> None:
    slots = storage.model_slots(DB_PATH, project_id)
    discipline = role_discipline(project_role)
    if project_role in DISCIPLINE_LEADS and discipline:
        if st.button(
            f"Submit {discipline} as Shared",
            key=f"submit-shared-{project_id}-{discipline}",
            disabled=(discipline, CDEState.WIP.value) not in slots,
            use_container_width=True,
        ):
            try:
                projects.submit_shared(
                    DB_PATH, project_id, discipline, project_role.value
                )
            except Exception as exc:
                st.error(f"Unable to submit Shared: {exc}")
            else:
                st.rerun()
    elif project_role is ProjectRole.PM_BIM:
        with st.popover("CDE model actions", use_container_width=True):
            for item_discipline in projects.DISCIPLINES:
                publish_column, archive_column = st.columns(2)
                if publish_column.button(
                    f"Publish {item_discipline}",
                    key=f"publish-{project_id}-{item_discipline}",
                    disabled=(item_discipline, CDEState.SHARED.value) not in slots,
                    use_container_width=True,
                ):
                    try:
                        projects.publish_model(
                            DB_PATH, project_id, item_discipline, project_role.value
                        )
                    except Exception as exc:
                        st.error(f"Unable to publish {item_discipline}: {exc}")
                    else:
                        st.rerun()
                if archive_column.button(
                    f"Archive {item_discipline}",
                    key=f"archive-{project_id}-{item_discipline}",
                    disabled=(item_discipline, CDEState.PUBLISHED.value) not in slots,
                    use_container_width=True,
                ):
                    try:
                        projects.archive_model(
                            DB_PATH, project_id, item_discipline, project_role.value
                        )
                    except Exception as exc:
                        st.error(f"Unable to archive {item_discipline}: {exc}")
                    else:
                        st.rerun()


def _display_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


def render_version_information(
    project_id: int,
    choice: tuple[tuple[str, CDEState], ...],
) -> None:
    records = storage.model_slots(DB_PATH, project_id)
    labels = {"ARC": "Architecture", "STR": "Structure", "MEP": "MEP"}
    with st.popover(
        "Info",
        help="Show revision, discipline, status, uploader, update time, and approver.",
        use_container_width=True,
    ):
        for index, (kind, cde_state) in enumerate(choice):
            record = records[(kind, cde_state.value)]
            generation = int(record.get("generation") or 1)
            if index:
                st.divider()
            st.markdown(
                f"**{labels[kind]} · G{generation:02d} · {cde_state.value}**"
            )
            st.caption(
                f"Created by: {record.get('created_by_role') or 'Legacy import'}  ·  "
                f"Updated: {_display_timestamp(record.get('updated_at'))}"
            )


def render_viewer(
    project_id: int,
    identity: Identity,
    project_role: ProjectRole,
) -> tuple[tuple[str, CDEState], ...]:
    render_model_actions(project_id, project_role)
    choices = model_choices(project_id, project_role)
    if not choices:
        st.info("No model slot is available for the current role.")
        return ()
    selector_key = f"viewer-models-{project_id}-{project_role.value}"
    override = st.session_state.pop("viewer_model_override", None)
    if override and override["project_id"] == project_id:
        override_choice = tuple(
            (discipline, CDEState(state))
            for discipline, state in override.get("slots", [])
        )
        if override_choice in choices:
            st.session_state[selector_key] = override_choice
    if st.session_state.get(selector_key) not in choices:
        shared_choices = [
            choice
            for choice in choices
            if all(state is CDEState.SHARED for _, state in choice)
        ]
        st.session_state[selector_key] = (
            max(shared_choices, key=len) if shared_choices else choices[0]
        )
    model_column, version_column = st.columns(
        [7.8, 1.2],
        gap="small",
        vertical_alignment="center",
    )
    with model_column:
        selected = st.selectbox(
            "Models",
            choices,
            format_func=_choice_label,
            key=selector_key,
            label_visibility="collapsed",
        )
    with version_column:
        render_version_information(project_id, selected)
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
    return selected

def render_notification_panel(project_id: int, project_role: ProjectRole) -> None:
    recipient_key = notification_recipient_key(project_role)
    if recipient_key is None:
        return
    notifications = storage.list_notifications(
        DB_PATH, project_id, recipient_key, limit=20
    )
    unread = storage.unread_notification_counts(DB_PATH, project_id).get(
        recipient_key, 0
    )
    label = f"Notifications · 🔴 {unread}" if unread else "Notifications"
    with st.expander(label, expanded=False):
        if not notifications:
            st.caption("No notifications yet.")
            return
        for notification in notifications:
            marker = "🔴 " if notification["read_at"] is None else ""
            if st.button(
                marker + notification["title"],
                key=f"notification-{notification['id']}",
                use_container_width=True,
            ):
                if notification["read_at"] is None:
                    storage.mark_notification_read(
                        DB_PATH, project_id, notification["id"]
                    )
                    storage.add_audit_event(
                        DB_PATH,
                        {
                            "project_id": project_id,
                            "agent_id": "application",
                            "declared_role": project_role.value,
                            "operation": "mark_notification_read",
                            "tool_parameters": {
                                "notification_id": notification["id"],
                                "recipient_key": recipient_key,
                            },
                            "result_summary": notification["title"],
                            "status": "completed",
                        },
                    )
                if notification["notification_type"] in {
                    "clash_run",
                    "clash_assignment",
                }:
                    st.session_state[f"expand-clash-{project_id}"] = True
                st.rerun()
            st.caption(_display_timestamp(notification["created_at"]))


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


def render_clash_issue_panel(project_id: int, project_role: ProjectRole) -> None:
    if (
        project_role is not ProjectRole.PM_BIM
        and project_role not in DISCIPLINE_LEADS
        and project_role not in MOD_ROLES
        and project_role not in CHECKER_ROLES
    ):
        return
    identity = ROLE_PROFILES[project_role].identity
    issues = [
        issue
        for issue in storage.list_clash_issues(DB_PATH, project_id, limit=50)
        if can_view_clash_issue(
            project_role,
            issue["model_a"],
            issue["model_b"],
            issue.get("assigned_to"),
        )
    ]
    active = [issue for issue in issues if issue["status"] != "resolved"]
    expand_key = f"expand-clash-{project_id}"
    expanded = bool(st.session_state.pop(expand_key, False))
    with st.expander(
        f"Clash issues ({len(active)} active / {len(issues)} total)",
        expanded=expanded,
    ):
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
            st.caption(
                f"{issue['model_a']}: {issue['element_a'].get('ifc_type')} · "
                f"GlobalId={issue['element_a'].get('global_id')}  |  "
                f"{issue['model_b']}: {issue['element_b'].get('ifc_type')} · "
                f"GlobalId={issue['element_b'].get('global_id')}"
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
                    "slots": [
                        (kind, CDEState.SHARED.value)
                        for kind in ("ARC", "STR", "MEP")
                        if kind in required
                    ],
                }
                st.rerun()
            st.divider()


def render_chat(
    project_id: int,
    project_role: ProjectRole,
    viewer_models: tuple[tuple[str, CDEState], ...],
) -> None:
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
    render_notification_panel(project_id, project_role)
    render_task_panel(project_id)
    render_clash_issue_panel(project_id, project_role)
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
        slot_records = storage.model_slots(DB_PATH, project_id)
        viewer_snapshot = tuple(
            ViewerModelSnapshot(
                discipline=discipline,
                cde_state=state,
                updated_at=slot_records[(discipline, state.value)]["updated_at"],
                generation=int(
                    slot_records[(discipline, state.value)]["generation"]
                ),
                size=Path(
                    slot_records[(discipline, state.value)]["path"]
                ).stat().st_size,
            )
            for discipline, state in viewer_models
        )
        selection = storage.get_selection(DB_PATH, project_id, identity)
        selected_slot = None
        if selection and selection.get("cde_state"):
            selected_slot = (
                selection["model_kind"],
                CDEState(selection["cde_state"]),
            )
        if selection and selected_slot in viewer_models:
            messages[-1] = {
                **messages[-1],
                "content": messages[-1]["content"]
                + "\n\nViewer selection supplied by the application: "
                f"{selection['model_kind']}.ifc, #{selection['step_id']}, "
                f"{selection.get('ifc_type')}, GlobalId={selection.get('global_id')}, "
                f"Name={selection.get('name')}.",
            }
        identity_prompt = storage.get_system_prompt(
            DB_PATH, project_id, identity, SYSTEM_PROMPTS[identity]
        )
        base_system_prompt = storage.get_system_prompt(
            DB_PATH, project_id, project_role, identity_prompt
        )
        viewer_states = {state for _, state in viewer_models}
        cde_state = next(iter(viewer_states)) if len(viewer_states) == 1 else None
        system_prompt = system_prompt_for_role(
            base_system_prompt,
            project_role,
            cde_state,
        )
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
                project_role=project_role,
                viewer_models=viewer_snapshot,
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

    with st.expander("System prompt for this project and role"):
        identity_prompt = storage.get_system_prompt(
            DB_PATH, project_id, identity, SYSTEM_PROMPTS[identity]
        )
        current_prompt = storage.get_system_prompt(
            DB_PATH, project_id, project_role, identity_prompt
        )
        edited_prompt = st.text_area(
            "System prompt",
            value=current_prompt,
            height=260,
            key=f"system-prompt-{project_id}-{project_role.value}",
        )
        if st.button(
            "Save system prompt",
            key=f"save-system-prompt-{project_id}-{project_role.value}",
            use_container_width=True,
        ):
            if not edited_prompt.strip():
                st.error("The system prompt cannot be empty.")
            else:
                storage.set_system_prompt(
                    DB_PATH, project_id, project_role, edited_prompt.strip()
                )
                st.success("System prompt saved for this project and role.")
        st.markdown("**Applied detailed role policy**")
        st.caption(f"{project_role.value}: {role_profile.prompt_policy}")
        if viewer_models:
            st.markdown("**Applied Viewer state policy**")
            for state in dict.fromkeys(state for _, state in viewer_models):
                st.caption(CDE_STATE_PROMPTS[state].strip())


def main() -> None:
    st.set_page_config(
        page_title="BIM Multi-Agent",
        page_icon="🏗️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    storage.init_db(DB_PATH)
    projects.migrate_legacy_ifc_slots(DB_PATH)
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
        viewer_models = render_viewer(project_id, identity, project_role)
    with chat_column:
        st.markdown(
            '<span class="chat-column-marker"></span>',
            unsafe_allow_html=True,
        )
        render_chat(project_id, project_role, viewer_models)


if __name__ == "__main__":
    main()
