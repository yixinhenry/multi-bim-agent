from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .domain import (
    ROLE_PROFILES,
    CDEState,
    Identity,
    ProjectRole,
    TaskStatus,
    can_view_role_context,
    role_conversation_key,
)


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_files (
    project_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    revision_number INTEGER NOT NULL DEFAULT 1,
    uploaded_by TEXT,
    approved_by TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, kind),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS model_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    discipline TEXT NOT NULL,
    cde_state TEXT NOT NULL,
    path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1,
    source_state TEXT,
    created_by_role TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, discipline, cde_state),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    identity TEXT NOT NULL,
    conversation_key TEXT NOT NULL DEFAULT 'main',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, identity, conversation_key),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    parent_task_id TEXT,
    conversation_id INTEGER,
    created_by TEXT NOT NULL,
    assigned_to TEXT NOT NULL,
    title TEXT NOT NULL,
    task_type TEXT NOT NULL DEFAULT 'analysis',
    target_files_json TEXT NOT NULL DEFAULT '[]',
    instructions TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(parent_task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS clash_runs (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    models_json TEXT NOT NULL,
    pair_counts_json TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    created_by_role TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS clash_issues (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    model_a TEXT NOT NULL,
    model_b TEXT NOT NULL,
    element_a_json TEXT NOT NULL,
    element_b_json TEXT NOT NULL,
    details_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    assigned_to TEXT,
    source_task_id TEXT,
    resolution_task_id TEXT,
    last_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(project_id, fingerprint),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(source_task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY(resolution_task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY(last_run_id) REFERENCES clash_runs(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS viewer_selections (
    project_id INTEGER NOT NULL,
    identity TEXT NOT NULL,
    model_kind TEXT NOT NULL,
    cde_state TEXT,
    step_id INTEGER NOT NULL,
    ifc_type TEXT,
    global_id TEXT,
    name TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, identity),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS conversation_prompts (
    project_id INTEGER NOT NULL,
    identity TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, identity),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    conversation_id INTEGER,
    agent_id TEXT NOT NULL,
    declared_role TEXT NOT NULL,
    task_id TEXT,
    target_file TEXT,
    operation TEXT NOT NULL,
    tool_parameters_json TEXT NOT NULL,
    input_message TEXT,
    result_summary TEXT,
    boundary_violation INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    recipient_key TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    title TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_id TEXT,
    created_at TEXT NOT NULL,
    read_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(db_path: Path) -> None:
    with closing(connect(db_path)) as connection:
        connection.executescript(SCHEMA)
        task_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        task_migrations = {
            "parent_task_id": "TEXT",
            "conversation_id": "INTEGER",
            "task_type": "TEXT NOT NULL DEFAULT 'analysis'",
            "target_files_json": "TEXT NOT NULL DEFAULT '[]'",
            "instructions": "TEXT NOT NULL DEFAULT ''",
            "error_text": "TEXT",
        }
        for column, definition in task_migrations.items():
            if column not in task_columns:
                connection.execute(
                    f"ALTER TABLE tasks ADD COLUMN {column} {definition}"
                )
        project_file_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(project_files)").fetchall()
        }
        project_file_migrations = {
            "revision_number": "INTEGER NOT NULL DEFAULT 1",
            "uploaded_by": "TEXT",
            "approved_by": "TEXT",
        }
        for column, definition in project_file_migrations.items():
            if column not in project_file_columns:
                connection.execute(
                    f"ALTER TABLE project_files ADD COLUMN {column} {definition}"
                )
        clash_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(clash_issues)").fetchall()
        }
        if "last_run_id" not in clash_columns:
            connection.execute("ALTER TABLE clash_issues ADD COLUMN last_run_id TEXT")
        selection_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(viewer_selections)").fetchall()
        }
        if "cde_state" not in selection_columns:
            connection.execute("ALTER TABLE viewer_selections ADD COLUMN cde_state TEXT")
        connection.execute(
            """
            INSERT OR IGNORE INTO model_slots(
                project_id, discipline, cde_state, path, original_filename,
                generation, source_state, created_by_role, updated_at
            )
            SELECT project_id, kind, 'WIP', path, original_filename,
                   revision_number, NULL, uploaded_by, updated_at
            FROM project_files
            WHERE kind IN ('ARC', 'STR', 'MEP')
            """
        )
        # Translate the exact application-generated legacy error prefix while
        # preserving user-authored messages in their original research language.
        connection.execute(
            """
            UPDATE messages
            SET content = 'Run failed: ' || substr(content, 6)
            WHERE role='assistant' AND content LIKE '运行失败：%'
            """
        )
        connection.commit()


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_project(db_path: Path, name: str, root_path: Path) -> int:
    timestamp = now()
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO projects(name, root_path, created_at) VALUES (?, ?, ?)",
            (name, str(root_path.resolve()), timestamp),
        )
        return int(cursor.lastrowid)


def list_projects(db_path: Path) -> list[dict[str, Any]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def get_project(db_path: Path, project_id: int) -> dict[str, Any]:
    with closing(connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ValueError(f"Project not found: {project_id}")
    return dict(row)


def upsert_project_file(
    db_path: Path,
    project_id: int,
    kind: str,
    path: Path,
    original_filename: str,
    uploaded_by: str | None = None,
) -> None:
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO project_files(
                project_id, kind, path, original_filename, revision_number,
                uploaded_by, approved_by, updated_at
            )
            VALUES (?, ?, ?, ?, 1, ?, NULL, ?)
            ON CONFLICT(project_id, kind) DO UPDATE SET
                path=excluded.path,
                original_filename=excluded.original_filename,
                revision_number=project_files.revision_number + 1,
                uploaded_by=excluded.uploaded_by,
                approved_by=NULL,
                updated_at=excluded.updated_at
            """,
            (
                project_id,
                kind,
                str(path.resolve()),
                original_filename,
                uploaded_by,
                now(),
            ),
        )


def project_files(db_path: Path, project_id: int) -> dict[str, dict[str, Any]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM project_files WHERE project_id = ?", (project_id,)
        ).fetchall()
    return {row["kind"]: dict(row) for row in rows}


def update_project_file_path(
    db_path: Path, project_id: int, kind: str, path: Path
) -> None:
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            "UPDATE project_files SET path=? WHERE project_id=? AND kind=?",
            (str(path.resolve()), project_id, kind),
        )


def _discipline_value(discipline: str) -> str:
    value = discipline.strip().upper()
    if value not in {"ARC", "STR", "MEP"}:
        raise ValueError("discipline must be ARC, STR, or MEP")
    return value


def _state_value(state: CDEState | str) -> str:
    if isinstance(state, CDEState):
        return state.value
    value = state.strip()
    for candidate in CDEState:
        if candidate.value.lower() == value.lower():
            return candidate.value
    raise ValueError("cde_state must be WIP, Shared, Published, or Archived")


def upsert_model_slot(
    db_path: Path,
    project_id: int,
    discipline: str,
    cde_state: CDEState | str,
    path: Path,
    original_filename: str,
    created_by_role: str | None = None,
    source_state: CDEState | str | None = None,
) -> dict[str, Any]:
    discipline_value = _discipline_value(discipline)
    state_value = _state_value(cde_state)
    source_value = _state_value(source_state) if source_state is not None else None
    timestamp = now()
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO model_slots(
                project_id, discipline, cde_state, path, original_filename,
                generation, source_state, created_by_role, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(project_id, discipline, cde_state) DO UPDATE SET
                path=excluded.path,
                original_filename=excluded.original_filename,
                generation=model_slots.generation + 1,
                source_state=excluded.source_state,
                created_by_role=excluded.created_by_role,
                updated_at=excluded.updated_at
            """,
            (
                project_id,
                discipline_value,
                state_value,
                str(path.resolve()),
                original_filename,
                source_value,
                created_by_role,
                timestamp,
            ),
        )
        row = connection.execute(
            """
            SELECT * FROM model_slots
            WHERE project_id=? AND discipline=? AND cde_state=?
            """,
            (project_id, discipline_value, state_value),
        ).fetchone()
    return dict(row)


def get_model_slot(
    db_path: Path,
    project_id: int,
    discipline: str,
    cde_state: CDEState | str,
) -> dict[str, Any] | None:
    with closing(connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT * FROM model_slots
            WHERE project_id=? AND discipline=? AND cde_state=?
            """,
            (project_id, _discipline_value(discipline), _state_value(cde_state)),
        ).fetchone()
    return _dict(row)


def update_model_slot_path(
    db_path: Path,
    project_id: int,
    discipline: str,
    cde_state: CDEState | str,
    path: Path,
) -> None:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE model_slots SET path=?
            WHERE project_id=? AND discipline=? AND cde_state=?
            """,
            (
                str(path.resolve()),
                project_id,
                _discipline_value(discipline),
                _state_value(cde_state),
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("model slot was not found")


def model_slots(
    db_path: Path,
    project_id: int,
) -> dict[tuple[str, str], dict[str, Any]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT * FROM model_slots
            WHERE project_id=?
            ORDER BY discipline, cde_state
            """,
            (project_id,),
        ).fetchall()
    return {(row["discipline"], row["cde_state"]): dict(row) for row in rows}


def ensure_conversation(
    db_path: Path,
    project_id: int,
    identity: Identity,
    conversation_key: str = "main",
) -> int:
    if not conversation_key.strip():
        raise ValueError("conversation_key cannot be empty")
    timestamp = now()
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO conversations(
                project_id, identity, conversation_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, identity.value, conversation_key, timestamp, timestamp),
        )
        row = connection.execute(
            """
            SELECT id FROM conversations
            WHERE project_id=? AND identity=? AND conversation_key=?
            """,
            (project_id, identity.value, conversation_key),
        ).fetchone()
    return int(row["id"])


def ensure_role_conversation(
    db_path: Path,
    project_id: int,
    role: ProjectRole,
) -> int:
    profile = ROLE_PROFILES[role]
    return ensure_conversation(
        db_path,
        project_id,
        profile.identity,
        conversation_key=role_conversation_key(role),
    )


def add_message(db_path: Path, conversation_id: int, role: str, content: str) -> int:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, now()),
        )
        connection.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (now(), conversation_id)
        )
        return int(cursor.lastrowid)


def list_messages(db_path: Path, conversation_id: int) -> list[dict[str, Any]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (conversation_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def list_role_context_messages(
    db_path: Path,
    project_id: int,
    viewer_role: ProjectRole,
    target_role: ProjectRole,
) -> list[dict[str, Any]]:
    """Read a role memory after enforcing the narrow lead visibility rule."""
    if not can_view_role_context(viewer_role, target_role):
        raise PermissionError(
            f"{viewer_role.value} cannot view the {target_role.value} context"
        )
    conversation_id = ensure_role_conversation(db_path, project_id, target_role)
    return list_messages(db_path, conversation_id)


def get_system_prompt(
    db_path: Path,
    project_id: int,
    identity: Identity | ProjectRole,
    default: str,
) -> str:
    with closing(connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT system_prompt FROM conversation_prompts
            WHERE project_id=? AND identity=?
            """,
            (project_id, identity.value),
        ).fetchone()
    return str(row["system_prompt"]) if row is not None else default


def set_system_prompt(
    db_path: Path,
    project_id: int,
    identity: Identity | ProjectRole,
    system_prompt: str,
) -> None:
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO conversation_prompts(project_id, identity, system_prompt, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id, identity) DO UPDATE SET
                system_prompt=excluded.system_prompt,
                updated_at=excluded.updated_at
            """,
            (project_id, identity.value, system_prompt, now()),
        )


def add_audit_event(db_path: Path, event: dict[str, Any]) -> str:
    event_id = event.get("id") or uuid4().hex
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO audit_events(
                id, project_id, conversation_id, agent_id, declared_role, task_id,
                target_file, operation, tool_parameters_json, input_message,
                result_summary, boundary_violation, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event["project_id"],
                event.get("conversation_id"),
                event["agent_id"],
                event["declared_role"],
                event.get("task_id"),
                event.get("target_file"),
                event["operation"],
                json.dumps(event.get("tool_parameters", {}), ensure_ascii=False, default=str),
                event.get("input_message"),
                event.get("result_summary"),
                int(bool(event.get("boundary_violation"))),
                event.get("status", "completed"),
                event.get("created_at", now()),
            ),
        )
    return event_id


def list_audit_events(
    db_path: Path, project_id: int, conversation_id: int | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    query = "SELECT * FROM audit_events WHERE project_id=?"
    parameters: list[Any] = [project_id]
    if conversation_id is not None:
        query += " AND conversation_id=?"
        parameters.append(conversation_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    parameters.append(limit)
    with closing(connect(db_path)) as connection:
        rows = connection.execute(query, parameters).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["tool_parameters"] = json.loads(item.pop("tool_parameters_json"))
        result.append(item)
    return result


def create_notification(
    db_path: Path,
    project_id: int,
    recipient_key: str,
    notification_type: str,
    title: str,
    payload: dict[str, Any] | None = None,
    source_id: str | None = None,
) -> str:
    notification_id = uuid4().hex
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO notifications(
                id, project_id, recipient_key, notification_type, title,
                payload_json, source_id, created_at, read_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                notification_id,
                project_id,
                recipient_key.strip(),
                notification_type.strip(),
                title.strip(),
                json.dumps(payload or {}, ensure_ascii=False, default=str),
                source_id,
                now(),
            ),
        )
    return notification_id


def list_notifications(
    db_path: Path,
    project_id: int,
    recipient_key: str,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM notifications WHERE project_id=? AND recipient_key=?"
    parameters: list[Any] = [project_id, recipient_key]
    if unread_only:
        query += " AND read_at IS NULL"
    query += " ORDER BY created_at DESC LIMIT ?"
    parameters.append(max(1, int(limit)))
    with closing(connect(db_path)) as connection:
        rows = connection.execute(query, parameters).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return result


def unread_notification_counts(db_path: Path, project_id: int) -> dict[str, int]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT recipient_key, COUNT(*) AS unread_count
            FROM notifications
            WHERE project_id=? AND read_at IS NULL
            GROUP BY recipient_key
            """,
            (project_id,),
        ).fetchall()
    return {str(row["recipient_key"]): int(row["unread_count"]) for row in rows}


def mark_notification_read(
    db_path: Path,
    project_id: int,
    notification_id: str,
) -> bool:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE notifications SET read_at=COALESCE(read_at, ?)
            WHERE id=? AND project_id=?
            """,
            (now(), notification_id, project_id),
        )
    return cursor.rowcount == 1


def set_selection(
    db_path: Path,
    project_id: int,
    identity: Identity,
    model_kind: str,
    step_id: int,
    ifc_type: str | None,
    global_id: str | None,
    name: str | None,
    cde_state: CDEState | str | None = None,
) -> None:
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO viewer_selections(
                project_id, identity, model_kind, cde_state, step_id, ifc_type,
                global_id, name, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, identity) DO UPDATE SET
                model_kind=excluded.model_kind, cde_state=excluded.cde_state,
                step_id=excluded.step_id,
                ifc_type=excluded.ifc_type, global_id=excluded.global_id,
                name=excluded.name, updated_at=excluded.updated_at
            """,
            (
                project_id,
                identity.value,
                model_kind,
                _state_value(cde_state) if cde_state is not None else None,
                step_id,
                ifc_type,
                global_id,
                name,
                now(),
            ),
        )


def get_selection(
    db_path: Path, project_id: int, identity: Identity
) -> dict[str, Any] | None:
    with closing(connect(db_path)) as connection:
        row = connection.execute(
            "SELECT * FROM viewer_selections WHERE project_id=? AND identity=?",
            (project_id, identity.value),
        ).fetchone()
    return _dict(row)


def create_task(
    db_path: Path,
    project_id: int,
    created_by: Identity,
    assigned_to: Identity,
    title: str,
    instructions: str,
    task_type: str = "analysis",
    target_files: list[str] | None = None,
    parent_task_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    clean_title = title.strip()
    clean_instructions = instructions.strip()
    if not clean_title:
        raise ValueError("task title cannot be empty")
    if not clean_instructions:
        raise ValueError("task instructions cannot be empty")
    if assigned_to not in {Identity.ARC, Identity.STR, Identity.MEP}:
        raise ValueError("tasks must be assigned to ARC, STR, or MEP")
    normalized_files = list(
        dict.fromkeys(Path(name).name for name in (target_files or []))
    )
    allowed_files = {"ARC.ifc", "STR.ifc", "MEP.ifc"}
    if any(name not in allowed_files for name in normalized_files):
        raise ValueError("target_files must contain ARC.ifc, STR.ifc, or MEP.ifc")

    task_id = uuid4().hex
    timestamp = now()
    with closing(connect(db_path)) as connection, connection:
        if parent_task_id:
            parent = connection.execute(
                "SELECT project_id FROM tasks WHERE id=?", (parent_task_id,)
            ).fetchone()
            if parent is None or int(parent["project_id"]) != project_id:
                raise ValueError("parent task must belong to the same project")
        connection.execute(
            """
            INSERT INTO tasks(
                id, project_id, parent_task_id, conversation_id, created_by,
                assigned_to, title, task_type, target_files_json, instructions,
                payload_json, status, result_json, error_text, created_at, updated_at
            ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                task_id,
                project_id,
                parent_task_id,
                created_by.value,
                assigned_to.value,
                clean_title,
                task_type.strip() or "analysis",
                json.dumps(normalized_files, ensure_ascii=False),
                clean_instructions,
                json.dumps(payload or {}, ensure_ascii=False, default=str),
                TaskStatus.PENDING.value,
                timestamp,
                timestamp,
            ),
        )
    return task_id


def _task_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["target_files"] = json.loads(item.pop("target_files_json") or "[]")
    item["payload"] = json.loads(item.pop("payload_json") or "{}")
    raw_result = item.pop("result_json")
    item["result"] = json.loads(raw_result) if raw_result else None
    return item


def get_task(db_path: Path, task_id: str) -> dict[str, Any]:
    with closing(connect(db_path)) as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
    task = _task_dict(row)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")
    return task


def list_tasks(
    db_path: Path,
    project_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT * FROM tasks
            WHERE project_id=?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (project_id, max(1, int(limit))),
        ).fetchall()
    tasks = []
    for row in rows:
        task = _task_dict(row)
        if task is not None:
            tasks.append(task)
    return tasks


def attach_task_conversation(
    db_path: Path,
    task_id: str,
    conversation_id: int,
) -> None:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            "UPDATE tasks SET conversation_id=?, updated_at=? WHERE id=?",
            (conversation_id, now(), task_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Task not found: {task_id}")


def start_task(db_path: Path, task_id: str) -> None:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE tasks SET status=?, error_text=NULL, updated_at=?
            WHERE id=? AND status=?
            """,
            (
                TaskStatus.RUNNING.value,
                now(),
                task_id,
                TaskStatus.PENDING.value,
            ),
        )
        if cursor.rowcount != 1:
            current = connection.execute(
                "SELECT status FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            if current is None:
                raise ValueError(f"Task not found: {task_id}")
            raise ValueError(
                f"Task {task_id} cannot start from status {current['status']}"
            )


def complete_task(
    db_path: Path,
    task_id: str,
    result: dict[str, Any],
) -> None:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE tasks
            SET status=?, result_json=?, error_text=NULL, updated_at=?
            WHERE id=? AND status=?
            """,
            (
                TaskStatus.COMPLETED.value,
                json.dumps(result, ensure_ascii=False, default=str),
                now(),
                task_id,
                TaskStatus.RUNNING.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Task {task_id} is not running")


def fail_task(db_path: Path, task_id: str, error: str) -> None:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE tasks
            SET status=?, error_text=?, updated_at=?
            WHERE id=? AND status IN (?, ?)
            """,
            (
                TaskStatus.FAILED.value,
                error[:12000],
                now(),
                task_id,
                TaskStatus.PENDING.value,
                TaskStatus.RUNNING.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Task {task_id} cannot be marked failed")

def create_clash_run(
    db_path: Path,
    project_id: int,
    models: list[dict[str, Any]],
    pair_counts: dict[str, int],
    parameters: dict[str, Any],
    created_by_role: str | None,
) -> str:
    run_id = uuid4().hex
    with closing(connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO clash_runs(
                id, project_id, models_json, pair_counts_json, parameters_json,
                created_by_role, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project_id,
                json.dumps(models, ensure_ascii=False, default=str),
                json.dumps(pair_counts, ensure_ascii=False, default=str),
                json.dumps(parameters, ensure_ascii=False, default=str),
                created_by_role,
                now(),
            ),
        )
    return run_id


def list_clash_runs(
    db_path: Path, project_id: int, limit: int = 50
) -> list[dict[str, Any]]:
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT * FROM clash_runs
            WHERE project_id=? ORDER BY created_at DESC LIMIT ?
            """,
            (project_id, max(1, int(limit))),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["models"] = json.loads(item.pop("models_json"))
        item["pair_counts"] = json.loads(item.pop("pair_counts_json"))
        item["parameters"] = json.loads(item.pop("parameters_json"))
        result.append(item)
    return result


def _clash_element_key(model: str, element: dict[str, Any]) -> str:
    identifier = element.get("global_id") or f"#{element.get('step_id')}"
    return f"{model}:{identifier}"


def upsert_clash_issues(
    db_path: Path,
    project_id: int,
    clashes: list[dict[str, Any]],
    source_task_id: str | None = None,
    last_run_id: str | None = None,
) -> list[str]:
    issue_ids = []
    timestamp = now()
    with closing(connect(db_path)) as connection, connection:
        for clash in clashes:
            pair = str(clash.get("pair", "")).split("-", 1)
            if len(pair) != 2:
                raise ValueError("clash pair must use MODEL-MODEL format")
            model_a, model_b = pair
            element_a = dict(clash.get("a") or {})
            element_b = dict(clash.get("b") or {})
            fingerprint = (
                f"{_clash_element_key(model_a, element_a)}|"
                f"{_clash_element_key(model_b, element_b)}"
            )
            issue_id = uuid4().hex
            title = (
                f"{model_a}-{model_b} clash: "
                f"{element_a.get('ifc_type')} #{element_a.get('step_id')} / "
                f"{element_b.get('ifc_type')} #{element_b.get('step_id')}"
            )
            connection.execute(
                """
                INSERT INTO clash_issues(
                    id, project_id, fingerprint, title, model_a, model_b,
                    element_a_json, element_b_json, details_json, status,
                    assigned_to, source_task_id, resolution_task_id, last_run_id,
                    created_at, updated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', NULL, ?, NULL, ?, ?, ?, ?)
                ON CONFLICT(project_id, fingerprint) DO UPDATE SET
                    title=excluded.title,
                    element_a_json=excluded.element_a_json,
                    element_b_json=excluded.element_b_json,
                    details_json=excluded.details_json,
                    status=CASE
                        WHEN clash_issues.status='resolved' THEN 'open'
                        ELSE clash_issues.status
                    END,
                    source_task_id=COALESCE(excluded.source_task_id, source_task_id),
                    last_run_id=COALESCE(excluded.last_run_id, last_run_id),
                    updated_at=excluded.updated_at,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    issue_id,
                    project_id,
                    fingerprint,
                    title,
                    model_a,
                    model_b,
                    json.dumps(element_a, ensure_ascii=False, default=str),
                    json.dumps(element_b, ensure_ascii=False, default=str),
                    json.dumps(clash, ensure_ascii=False, default=str),
                    source_task_id,
                    last_run_id,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                """
                SELECT id FROM clash_issues
                WHERE project_id=? AND fingerprint=?
                """,
                (project_id, fingerprint),
            ).fetchone()
            issue_ids.append(str(row["id"]))
    return issue_ids


def resolve_missing_clash_issues(
    db_path: Path,
    project_id: int,
    model_pairs: list[tuple[str, str]],
    active_issue_ids: list[str],
) -> int:
    resolved = 0
    with closing(connect(db_path)) as connection, connection:
        for model_a, model_b in model_pairs:
            parameters: list[Any] = [now(), project_id, model_a, model_b]
            query = """
                UPDATE clash_issues
                SET status='resolved', updated_at=?
                WHERE project_id=? AND model_a=? AND model_b=?
                  AND status IN ('open', 'assigned')
            """
            if active_issue_ids:
                placeholders = ", ".join("?" for _ in active_issue_ids)
                query += f" AND id NOT IN ({placeholders})"
                parameters.extend(active_issue_ids)
            resolved += connection.execute(query, parameters).rowcount
    return resolved


def list_clash_issues(
    db_path: Path,
    project_id: int,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM clash_issues WHERE project_id=?"
    parameters: list[Any] = [project_id]
    if status is not None:
        query += " AND status=?"
        parameters.append(status)
    query += " ORDER BY updated_at DESC LIMIT ?"
    parameters.append(max(1, int(limit)))
    with closing(connect(db_path)) as connection:
        rows = connection.execute(query, parameters).fetchall()
    issues = []
    for row in rows:
        issue = dict(row)
        issue["element_a"] = json.loads(issue.pop("element_a_json"))
        issue["element_b"] = json.loads(issue.pop("element_b_json"))
        issue["details"] = json.loads(issue.pop("details_json"))
        issues.append(issue)
    return issues


def assign_clash_issues(
    db_path: Path,
    project_id: int,
    issue_ids: list[str],
    assigned_to: str,
) -> int:
    normalized_ids = list(dict.fromkeys(item.strip() for item in issue_ids if item.strip()))
    if not normalized_ids:
        raise ValueError("issue_ids cannot be empty")
    discipline = _discipline_value(assigned_to)
    placeholders = ", ".join("?" for _ in normalized_ids)
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            f"""
            UPDATE clash_issues
            SET assigned_to=?,
                status=CASE WHEN status='resolved' THEN status ELSE 'assigned' END,
                updated_at=?
            WHERE project_id=? AND id IN ({placeholders})
            """,
            [discipline, now(), project_id, *normalized_ids],
        )
    return cursor.rowcount


def link_clash_issue_task(
    db_path: Path,
    issue_id: str,
    task_id: str,
) -> None:
    with closing(connect(db_path)) as connection, connection:
        row = connection.execute(
            """
            SELECT i.project_id, t.project_id AS task_project_id, t.assigned_to
            FROM clash_issues i
            JOIN tasks t ON t.id=?
            WHERE i.id=?
            """,
            (task_id, issue_id),
        ).fetchone()
        if row is None:
            raise ValueError("clash issue or task was not found")
        if int(row["project_id"]) != int(row["task_project_id"]):
            raise ValueError("clash issue and task must belong to the same project")
        connection.execute(
            """
            UPDATE clash_issues
            SET status='assigned', assigned_to=?, resolution_task_id=?, updated_at=?
            WHERE id=?
            """,
            (row["assigned_to"], task_id, now(), issue_id),
        )


def resolve_clash_issue(db_path: Path, issue_id: str) -> None:
    with closing(connect(db_path)) as connection, connection:
        cursor = connection.execute(
            """
            UPDATE clash_issues SET status='resolved', updated_at=?
            WHERE id=? AND status IN ('open', 'assigned')
            """,
            (now(), issue_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Clash issue {issue_id} cannot be resolved")
