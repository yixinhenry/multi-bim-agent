from __future__ import annotations

import json
import re
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import projects, storage
from .domain import Identity, PROFILES, expected_access


@dataclass(frozen=True)
class ToolContext:
    db_path: Path
    project_id: int
    conversation_id: int
    identity: Identity
    input_message: str
    user_identity: Identity | None = None
    task_id: str | None = None
    ifc_write_allowed: bool = True
    event_callback: Callable[[str, str, dict[str, Any]], None] | None = None

    @property
    def acting_user_identity(self) -> Identity:
        """Return the user whose permissions govern this agent execution."""
        return self.user_identity or self.identity

    @property
    def can_edit_ifc(self) -> bool:
        return (
            self.ifc_write_allowed
            and self.acting_user_identity is not Identity.CLIENT
        )


class IFCResearchTools:
    """IFC tools with discipline-boundary enforcement and audit logging."""

    def __init__(self, context: ToolContext):
        self.context = context

    def _emit(self, event: str, message: str, payload: dict[str, Any] | None = None) -> None:
        if self.context.event_callback is not None:
            self.context.event_callback(event, message, payload or {})

    def _execute(
        self,
        file_name: str,
        operation: str,
        parameters: dict[str, Any],
        callback: Callable[[Path], Any],
    ) -> str:
        profile = PROFILES[self.context.identity]
        target = Path(file_name).name
        violation = not expected_access(self.context.identity, target, operation)
        if violation:
            summary = (
                f"{profile.declared_role} is not allowed to run {operation} "
                f"on {target}"
            )
            self._audit(
                profile,
                target,
                operation,
                parameters,
                summary,
                True,
                "error",
            )
            raise PermissionError(summary)
        self._emit(
            "tool_started",
            f"Calling {operation} on {target}",
            {"tool": operation, "target_file": target, "parameters": parameters},
        )
        try:
            _, path = projects.resolve_ifc(
                self.context.db_path, self.context.project_id, target
            )
            result = callback(path)
            summary = result if isinstance(result, str) else json.dumps(
                result, ensure_ascii=False, default=str
            )
            status = "completed"
        except Exception as exc:
            summary = f"{type(exc).__name__}: {exc}"
            status = "error"
            self._audit(profile, target, operation, parameters, summary, violation, status)
            self._emit(
                "tool_failed",
                f"{operation} failed for {target}: {exc}",
                {"tool": operation, "target_file": target, "error": str(exc)},
            )
            raise
        self._audit(profile, target, operation, parameters, summary, violation, status)
        self._emit(
            "tool_completed",
            f"Completed {operation} on {target}",
            {"tool": operation, "target_file": target},
        )
        return summary

    def _audit(
        self,
        profile,
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

    @staticmethod
    def _open(path: Path):
        try:
            import ifcopenshell
        except ImportError as exc:
            raise RuntimeError("IfcOpenShell is not installed") from exc
        return ifcopenshell.open(str(path))

    def read_ifc(self, file_name: str) -> str:
        def overview(path: Path) -> dict[str, Any]:
            model = self._open(path)
            counts: dict[str, int] = {}
            for entity in model:
                entity_type = entity.is_a()
                counts[entity_type] = counts.get(entity_type, 0) + 1
            return {
                "file": path.name,
                "schema": model.schema,
                "entity_count": sum(counts.values()),
                "common_types": sorted(
                    counts.items(), key=lambda item: item[1], reverse=True
                )[:20],
            }

        return self._execute(file_name, "read_ifc", {}, overview)

    def query_ifc(self, file_name: str, query: str) -> str:
        def run(path: Path) -> dict[str, Any]:
            model = self._open(path)
            stripped = query.strip()
            if stripped.startswith("#") and stripped[1:].isdigit():
                entity = model.by_id(int(stripped[1:]))
                return entity.get_info(recursive=False) if entity else {"found": False}
            if len(stripped) == 22:
                entity = model.by_guid(stripped)
                return entity.get_info(recursive=False) if entity else {"found": False}
            if not re.fullmatch(r"Ifc[A-Za-z0-9_]+", stripped):
                return {
                    "query": stripped,
                    "error": "query must be an IFC type, #STEP id, or GlobalId",
                }
            try:
                all_entities = model.by_type(stripped)
            except RuntimeError:
                return {
                    "query": stripped,
                    "error": f"Unknown IFC type: {stripped}",
                }
            entities = all_entities[:100]
            return {
                "query": stripped,
                "count_returned": len(entities),
                "truncated": len(all_entities) > 100,
                "entities": [
                    {
                        "step_id": item.id(),
                        "ifc_type": item.is_a(),
                        "GlobalId": getattr(item, "GlobalId", None),
                        "Name": getattr(item, "Name", None),
                    }
                    for item in entities
                ],
            }

        return self._execute(file_name, "query_ifc", {"query": query}, run)

    def edit_ifc(self, file_name: str, patch: dict[str, Any]) -> str:
        if not self.context.can_edit_ifc:
            raise PermissionError("The current user is not allowed to modify IFC models")

        def edit(path: Path) -> dict[str, Any]:
            model = self._open(path)
            entity = None
            if patch.get("global_id"):
                entity = model.by_guid(str(patch["global_id"]))
            elif patch.get("step_id") is not None:
                entity = model.by_id(int(patch["step_id"]))
            if entity is None:
                raise ValueError("patch target was not found")
            attribute = str(patch.get("attribute", ""))
            if attribute not in {"Name", "Description", "ObjectType", "LongName", "Tag"}:
                raise ValueError("unsupported editable attribute")
            if not hasattr(entity, attribute):
                raise ValueError(f"{entity.is_a()} has no {attribute} attribute")
            old_value = getattr(entity, attribute)
            setattr(entity, attribute, patch.get("value"))
            temporary = path.with_suffix(".ifc.editing")
            model.write(str(temporary))
            temporary.replace(path)
            path.with_suffix(".frag").unlink(missing_ok=True)
            return {
                "file": path.name,
                "step_id": entity.id(),
                "ifc_type": entity.is_a(),
                "attribute": attribute,
                "old_value": old_value,
                "new_value": patch.get("value"),
            }

        return self._execute(file_name, "edit_ifc", {"patch": patch}, edit)

    def run_clash_detection(
        self,
        file_names: list[str] | None = None,
        tolerance: float = 0.002,
        limit: int = 200,
    ) -> str:
        """Check world-coordinate AABB overlaps across uploaded IFC models."""
        available = storage.project_files(
            self.context.db_path, self.context.project_id
        )
        if file_names:
            requested = [Path(name).name for name in file_names]
        else:
            requested = [
                f"{kind}.ifc" for kind in ("ARC", "STR", "MEP") if kind in available
            ]
        requested = list(dict.fromkeys(requested))
        if len(requested) < 2:
            raise ValueError(
                "Clash detection requires any two uploaded discipline models; "
                f"available models: {requested or 'none'}"
            )
        resolved = [
            projects.resolve_ifc(self.context.db_path, self.context.project_id, name)
            for name in requested
        ]
        profile = PROFILES[self.context.identity]
        outside = [
            f"{kind}.ifc"
            for kind, _ in resolved
            if f"{kind}.ifc" not in profile.expected_files
        ]
        # Project Manager/Client runs are coordination operations, not direct-file
        # tool calls. Discipline agents retain boundary-violation semantics.
        violation = self.context.identity not in {
            Identity.CLIENT,
            Identity.PROJECT_MANAGER,
        } and bool(outside)
        parameters = {
            "file_names": requested,
            "tolerance": float(tolerance),
            "limit": int(limit),
        }
        self._emit(
            "tool_started",
            f"Calling run_clash_detection on {', '.join(requested)}",
            {
                "tool": "run_clash_detection",
                "target_files": requested,
                "parameters": parameters,
            },
        )
        try:
            import ifcopenshell
            import ifcopenshell.geom

            settings = ifcopenshell.geom.settings()
            settings.set(settings.USE_WORLD_COORDS, True)
            model_data = []
            for kind, path in resolved:
                model = ifcopenshell.open(str(path))
                products = [
                    entity
                    for entity in model.by_type("IfcProduct")
                    if getattr(entity, "Representation", None) is not None
                    and getattr(entity, "GlobalId", None)
                    and not entity.is_a("IfcSpace")
                ]
                metadata = {
                    entity.GlobalId: {
                        "step_id": entity.id(),
                        "ifc_type": entity.is_a(),
                        "global_id": entity.GlobalId,
                        "name": getattr(entity, "Name", None),
                    }
                    for entity in products
                }
                boxes = []
                iterator = ifcopenshell.geom.iterator(
                    settings,
                    model,
                    max(1, os.cpu_count() or 1),
                    include=products,
                )
                if iterator.initialize():
                    while True:
                        shape = iterator.get()
                        vertices = shape.geometry.verts
                        xs = vertices[0::3]
                        ys = vertices[1::3]
                        zs = vertices[2::3]
                        element = metadata.get(shape.guid)
                        if element is not None and xs and ys and zs:
                            boxes.append(
                                (
                                    (
                                        min(xs), min(ys), min(zs),
                                        max(xs), max(ys), max(zs),
                                    ),
                                    element,
                                )
                            )
                        if not iterator.next():
                            break
                model_data.append((kind, boxes))

            results = []
            pair_counts = {}
            threshold = float(tolerance)
            for index, (kind_a, boxes_a) in enumerate(model_data):
                for kind_b, boxes_b in model_data[index + 1 :]:
                    pair_name = f"{kind_a}-{kind_b}"
                    pair_count = 0
                    for bounds_a, element_a in boxes_a:
                        for bounds_b, element_b in boxes_b:
                            overlap = all(
                                min(bounds_a[axis + 3], bounds_b[axis + 3])
                                - max(bounds_a[axis], bounds_b[axis])
                                > threshold
                                for axis in range(3)
                            )
                            if not overlap:
                                continue
                            pair_count += 1
                            if len(results) < max(0, int(limit)):
                                results.append(
                                    {
                                        "pair": pair_name,
                                        "a": element_a,
                                        "b": element_b,
                                        "distance": 0.0,
                                        "method": "AABB",
                                    }
                                )
                    pair_counts[pair_name] = pair_count
            issue_ids = storage.upsert_clash_issues(
                self.context.db_path,
                self.context.project_id,
                results,
                source_task_id=self.context.task_id,
            )
            total_clashes = sum(pair_counts.values())
            truncated = total_clashes > len(results)
            resolved_issue_count = 0
            if not truncated:
                resolved_issue_count = storage.resolve_missing_clash_issues(
                    self.context.db_path,
                    self.context.project_id,
                    [tuple(pair.split("-", 1)) for pair in pair_counts],
                    issue_ids,
                )
            payload = {
                "models_checked": requested,
                "pair_counts": pair_counts,
                "total_clashes": total_clashes,
                "returned_clashes": len(results),
                "truncated": truncated,
                "clashes": results,
                "issue_ids": issue_ids,
                "resolved_issue_count": resolved_issue_count,
                "detection_method": "world-coordinate AABB overlap",
            }
            summary = json.dumps(payload, ensure_ascii=False, default=str)
            status = "completed"
        except Exception as exc:
            summary = f"{type(exc).__name__}: {exc}"
            status = "error"
            self._audit(
                profile,
                ", ".join(requested),
                "run_clash_detection",
                parameters,
                summary,
                violation,
                status,
            )
            self._emit(
                "tool_failed",
                f"Clash detection failed: {exc}",
                {"tool": "run_clash_detection", "error": str(exc)},
            )
            raise
        self._audit(
            profile,
            ", ".join(requested),
            "run_clash_detection",
            parameters,
            summary,
            violation,
            status,
        )
        self._emit(
            "tool_completed",
            (
                "Completed clash detection: "
                f"{sum(pair_counts.values())} clash(es) across {len(pair_counts)} model pair(s)"
            ),
            {
                "tool": "run_clash_detection",
                "target_files": requested,
                "pair_counts": pair_counts,
            },
        )
        return summary
