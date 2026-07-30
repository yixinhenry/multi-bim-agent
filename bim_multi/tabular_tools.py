from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

from . import projects, storage
from .domain import Identity, PROFILES
from .ifc_tools import ToolContext


class ProjectDataTools:
    """Audited Cost.csv and Schedule.csv inspection tools."""

    def __init__(self, context: ToolContext):
        self.context = context

    def summarize_project_csv(
        self,
        file_name: str,
        limit: int = 20,
    ) -> str:
        def summarize(path: Path) -> dict[str, Any]:
            columns, rows, encoding = self._read_rows(path)
            numeric = {}
            for column in columns:
                values = []
                for row in rows:
                    parsed = self._number(row.get(column, ""))
                    if parsed is not None:
                        values.append(parsed)
                if values:
                    numeric[column] = {
                        "numeric_rows": len(values),
                        "total": sum(values),
                        "minimum": min(values),
                        "maximum": max(values),
                    }
            bounded = max(0, min(int(limit), 100))
            return {
                "file": path.name,
                "encoding": encoding,
                "columns": columns,
                "row_count": len(rows),
                "numeric_columns": numeric,
                "sample_rows": rows[:bounded],
                "sample_truncated": len(rows) > bounded,
            }

        return self._execute(
            file_name,
            "summarize_project_csv",
            {"limit": limit},
            summarize,
        )

    def query_project_csv(
        self,
        file_name: str,
        column: str,
        value: str,
        limit: int = 50,
    ) -> str:
        def query(path: Path) -> dict[str, Any]:
            columns, rows, encoding = self._read_rows(path)
            if column not in columns:
                raise ValueError(
                    f"Unknown column {column!r}; available columns: {columns}"
                )
            needle = value.casefold()
            matched = [
                row
                for row in rows
                if needle in str(row.get(column, "")).casefold()
            ]
            bounded = max(1, min(int(limit), 200))
            return {
                "file": path.name,
                "encoding": encoding,
                "column": column,
                "value": value,
                "matched_count": len(matched),
                "rows": matched[:bounded],
                "truncated": len(matched) > bounded,
            }

        return self._execute(
            file_name,
            "query_project_csv",
            {"column": column, "value": value, "limit": limit},
            query,
        )

    def analyze_ifc_csv_mapping(
        self,
        file_name: str,
        ifc_file_name: str,
        csv_column: str,
        ifc_field: str = "GlobalId",
        limit: int = 20,
    ) -> str:
        def analyze(path: Path) -> dict[str, Any]:
            columns, rows, _ = self._read_rows(path)
            if csv_column not in columns:
                raise ValueError(
                    f"Unknown column {csv_column!r}; available columns: {columns}"
                )
            if ifc_field not in {"GlobalId", "Tag", "Name"}:
                raise ValueError("ifc_field must be GlobalId, Tag, or Name")
            _, ifc_path = projects.resolve_ifc(
                self.context.db_path,
                self.context.project_id,
                ifc_file_name,
            )
            try:
                import ifcopenshell
            except ImportError as exc:
                raise RuntimeError("IfcOpenShell is not installed") from exc
            model = ifcopenshell.open(str(ifc_path))
            elements = {}
            for entity in model.by_type("IfcProduct"):
                value = getattr(entity, ifc_field, None)
                if value is not None and str(value).strip():
                    elements[str(value).strip().casefold()] = {
                        "step_id": entity.id(),
                        "ifc_type": entity.is_a(),
                        "global_id": getattr(entity, "GlobalId", None),
                        "name": getattr(entity, "Name", None),
                    }
            matched = []
            unmatched = []
            for row in rows:
                key = str(row.get(csv_column, "")).strip()
                element = elements.get(key.casefold()) if key else None
                if element is None:
                    unmatched.append(key)
                elif len(matched) < max(0, min(int(limit), 100)):
                    matched.append({"csv_value": key, "ifc": element})
            matched_count = len(rows) - len(unmatched)
            return {
                "csv_file": path.name,
                "ifc_file": ifc_path.name,
                "csv_column": csv_column,
                "ifc_field": ifc_field,
                "row_count": len(rows),
                "matched_rows": matched_count,
                "unmatched_rows": len(unmatched),
                "coverage": matched_count / len(rows) if rows else 0.0,
                "matched_examples": matched,
                "unmatched_examples": unmatched[: max(0, min(int(limit), 100))],
            }

        return self._execute(
            file_name,
            "analyze_ifc_csv_mapping",
            {
                "ifc_file_name": ifc_file_name,
                "csv_column": csv_column,
                "ifc_field": ifc_field,
                "limit": limit,
            },
            analyze,
        )

    def _execute(
        self,
        file_name: str,
        operation: str,
        parameters: dict[str, Any],
        callback: Callable[[Path], dict[str, Any]],
    ) -> str:
        target = Path(file_name).name
        profile = PROFILES[self.context.identity]
        violation = self.context.identity not in {
            Identity.CLIENT,
            Identity.PROJECT_MANAGER,
        }
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
            _, path = projects.resolve_csv(
                self.context.db_path,
                self.context.project_id,
                target,
            )
            result = callback(path)
            summary = json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            summary = f"{type(exc).__name__}: {exc}"
            self._audit(
                profile,
                target,
                operation,
                parameters,
                summary,
                violation,
                "error",
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
            operation,
            parameters,
            summary,
            violation,
            "completed",
        )
        self._emit(
            "tool_completed",
            f"Completed {operation} on {target}",
            {"tool": operation, "target_file": target},
        )
        return summary

    @staticmethod
    def _read_rows(
        path: Path,
    ) -> tuple[list[str], list[dict[str, str]], str]:
        last_error = None
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                with path.open("r", encoding=encoding, newline="") as handle:
                    reader = csv.DictReader(handle)
                    columns = list(reader.fieldnames or [])
                    if not columns:
                        raise ValueError("CSV has no header row")
                    rows = [
                        {
                            str(key): "" if value is None else str(value)
                            for key, value in row.items()
                        }
                        for row in reader
                    ]
                return columns, rows, encoding
            except UnicodeDecodeError as exc:
                last_error = exc
        raise ValueError(f"Unable to decode CSV: {last_error}")

    @staticmethod
    def _number(value: str) -> float | None:
        cleaned = value.strip().replace(",", "")
        for token in ("$", "GBP", "USD", "CNY", "RMB"):
            cleaned = cleaned.replace(token, "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _audit(
        self,
        profile: Any,
        target: str,
        operation: str,
        parameters: dict[str, Any],
        summary: str,
        violation: bool,
        status: str,
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
