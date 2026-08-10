from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from . import projects, storage
from .domain import PROFILES, expected_access
from .ifc_tools import ToolContext



_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())


class IfcMCPAdapter:
    """Audited ifcMCP query and isolated edit sessions for one explicit model."""

    def __init__(
        self,
        context: ToolContext,
        session_factory: Callable[[], Any] | None = None,
    ):
        self.context = context
        self._session_factory = session_factory or self._default_session_factory

    @staticmethod
    def _default_session_factory() -> Any:
        try:
            from ifcmcp.core import IfcSession
        except ImportError as exc:
            raise RuntimeError("ifcopenshell-mcp is not installed") from exc
        return IfcSession()

    def edit_docs(self, function_path: str) -> str:
        result = self._session_factory().ifc_docs(function_path)
        return json.dumps(result, ensure_ascii=False, default=str)

    def summary(self, file_name: str) -> str:
        return self._query(
            file_name,
            "ifcmcp_summary",
            {},
            lambda session: session.ifc_summary(),
        )

    def info(self, file_name: str, element_id: int) -> str:
        return self._query(
            file_name,
            "ifcmcp_info",
            {"element_id": int(element_id)},
            lambda session: session.ifc_info(int(element_id)),
        )

    def relations(
        self,
        file_name: str,
        element_id: int,
        traverse: str = "",
    ) -> str:
        return self._query(
            file_name,
            "ifcmcp_relations",
            {"element_id": int(element_id), "traverse": traverse},
            lambda session: session.ifc_relations(int(element_id), traverse),
        )

    def select(
        self,
        file_name: str,
        query: str,
        limit: int = 100,
    ) -> str:
        bounded = max(1, min(int(limit), 500))

        def run(session: Any) -> dict[str, Any]:
            matches = session.ifc_select(query)
            return {
                "query": query,
                "matched_count": len(matches),
                "returned_count": min(len(matches), bounded),
                "truncated": len(matches) > bounded,
                "elements": matches[:bounded],
            }

        return self._query(
            file_name,
            "ifcmcp_select",
            {"query": query, "limit": bounded},
            run,
        )

    def _query(
        self,
        file_name: str,
        operation: str,
        parameters: dict[str, Any],
        callback: Callable[[Any], Any],
    ) -> str:
        target = Path(file_name).name
        profile = PROFILES[self.context.identity]
        violation = not expected_access(
            self.context.identity,
            target,
            "read_ifc",
        )
        if violation:
            summary = f"{profile.declared_role} is not allowed to query {target}"
            self._audit(
                profile,
                target,
                parameters,
                summary,
                True,
                "error",
                operation=operation,
            )
            raise PermissionError(summary)

        self._emit(
            "tool_started",
            f"Calling {operation} on {target}",
            {
                "tool": operation,
                "target_file": target,
                "parameters": parameters,
            },
        )
        try:
            _, path = projects.resolve_ifc(
                self.context.db_path,
                self.context.project_id,
                target,
            )
            session = self._session_factory()
            session.ifc_load(str(path))
            result = callback(session)
            summary = json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            summary = f"{type(exc).__name__}: {exc}"
            self._audit(
                profile,
                target,
                parameters,
                summary,
                False,
                "error",
                operation=operation,
            )
            self._emit(
                "tool_failed",
                f"{operation} failed for {target}: {exc}",
                {
                    "tool": operation,
                    "target_file": target,
                    "error": str(exc),
                },
            )
            raise

        self._audit(
            profile,
            target,
            parameters,
            summary,
            False,
            "completed",
            operation=operation,
        )
        self._emit(
            "tool_completed",
            f"Completed {operation} on {target}",
            {"tool": operation, "target_file": target},
        )
        return summary

    def edit(
        self,
        file_name: str,
        function_path: str,
        params: dict[str, Any],
    ) -> str:
        if not self.context.can_edit_ifc:
            raise PermissionError("The current user is not allowed to modify IFC models")

        target = Path(file_name).name
        profile = PROFILES[self.context.identity]
        violation = not expected_access(
            self.context.identity,
            target,
            "edit_ifc",
        )
        parameters = {
            "function_path": function_path,
            "params": params,
        }
        if violation:
            summary = (
                f"{profile.declared_role} is not allowed to modify {target}"
            )
            self._audit(
                profile,
                target,
                parameters,
                summary,
                True,
                "error",
            )
            raise PermissionError(summary)
        self._emit(
            "tool_started",
            f"Calling ifcMCP {function_path} on {target}",
            {
                "tool": "ifcmcp_edit",
                "target_file": target,
                "parameters": parameters,
            },
        )
        try:
            _, path = projects.resolve_ifc(
                self.context.db_path,
                self.context.project_id,
                target,
            )
            result = self._edit_isolated(path, function_path, params)
            summary = json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            summary = f"{type(exc).__name__}: {exc}"
            self._audit(
                profile,
                target,
                parameters,
                summary,
                violation,
                "error",
            )
            self._emit(
                "tool_failed",
                f"ifcMCP edit failed for {target}: {exc}",
                {
                    "tool": "ifcmcp_edit",
                    "target_file": target,
                    "error": str(exc),
                },
            )
            raise

        self._audit(
            profile,
            target,
            parameters,
            summary,
            violation,
            "completed",
        )
        self._emit(
            "tool_completed",
            f"Completed ifcMCP {function_path} on {target}",
            {
                "tool": "ifcmcp_edit",
                "target_file": target,
                "function_path": function_path,
            },
        )
        return summary

    def _edit_isolated(
        self,
        path: Path,
        function_path: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        lock = _path_lock(path)
        with lock:
            temporary = path.with_name(
                f".{path.name}.{self.context.task_id or uuid4().hex}.mcp-editing"
            )
            temporary.unlink(missing_ok=True)
            try:
                session = self._session_factory()
                loaded = session.ifc_load(str(path))
                edit_result = session.ifc_edit(
                    function_path,
                    {
                        key: (
                            json.dumps(value, ensure_ascii=False)
                            if isinstance(value, (dict, list, tuple))
                            else str(value)
                        )
                        for key, value in params.items()
                    },
                )
                if not isinstance(edit_result, dict) or not edit_result.get("ok"):
                    error = (
                        edit_result.get("error")
                        if isinstance(edit_result, dict)
                        else "invalid ifcMCP edit result"
                    )
                    raise RuntimeError(str(error))
                session.ifc_save(str(temporary))

                verifier = self._session_factory()
                verification = verifier.ifc_load(str(temporary))
                temporary.replace(path)
                path.with_suffix(".frag").unlink(missing_ok=True)
                return {
                    "file": path.name,
                    "function_path": function_path,
                    "params": params,
                    "edit_result": edit_result.get("result"),
                    "loaded": loaded,
                    "verification": verification,
                    "session_isolation": "one session per edit call",
                }
            finally:
                temporary.unlink(missing_ok=True)

    def _audit(
        self,
        profile: Any,
        target: str,
        parameters: dict[str, Any],
        summary: str,
        violation: bool,
        status: str,
        operation: str = "ifcmcp_edit",
    ) -> None:
        storage.add_audit_event(
            self.context.db_path,
            {
                "project_id": self.context.project_id,
                "conversation_id": self.context.conversation_id,
                "agent_id": profile.agent_id,
                "declared_role": profile.declared_role,
                "task_id": self.context.task_id,
                "target_file": target,
                "operation": operation,
                "tool_parameters": parameters,
                "input_message": self.context.input_message,
                "result_summary": summary[:12000],
                "boundary_violation": violation,
                "status": status,
            },
        )

    def _emit(
        self,
        event: str,
        message: str,
        payload: dict[str, Any],
    ) -> None:
        if self.context.event_callback is not None:
            self.context.event_callback(event, message, payload)
