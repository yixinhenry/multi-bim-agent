from __future__ import annotations

import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest

from bim_multi import projects, storage
from bim_multi.domain import Identity
from bim_multi.ifc_tools import ToolContext
from bim_multi.tabular_tools import ProjectDataTools


def make_data_context(
    tmp_path: Path,
    identity: Identity = Identity.PROJECT_MANAGER,
) -> ToolContext:
    db_path = tmp_path / "app.db"
    project_dir = tmp_path / "projects"
    storage.init_db(db_path)
    project_id = projects.create(db_path, project_dir, "Project")
    projects.save_upload(
        db_path,
        project_id,
        "COST",
        "estimate.csv",
        BytesIO(
            b"Code,Description,Quantity,UnitCost\n"
            b"A1,Wall,10,25.5\n"
            b"M1,Duct,5,100\n"
        ),
    )
    conversation_id = storage.ensure_conversation(
        db_path,
        project_id,
        identity,
    )
    return ToolContext(
        db_path=db_path,
        project_id=project_id,
        conversation_id=conversation_id,
        identity=identity,
        input_message="Review project cost data.",
    )


def test_cost_csv_summary_and_query_are_audited(tmp_path: Path) -> None:
    context = make_data_context(tmp_path)
    tools = ProjectDataTools(context)

    summary = json.loads(tools.summarize_project_csv("Cost.csv"))
    assert summary["row_count"] == 2
    assert summary["numeric_columns"]["Quantity"]["total"] == 15.0
    assert summary["numeric_columns"]["UnitCost"]["total"] == 125.5

    query = json.loads(
        tools.query_project_csv("Cost.csv", "Description", "duct")
    )
    assert query["matched_count"] == 1
    assert query["rows"][0]["Code"] == "M1"

    events = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )
    assert {event["operation"] for event in events} == {
        "summarize_project_csv",
        "query_project_csv",
    }
    assert all(event["boundary_violation"] == 0 for event in events)


def test_discipline_csv_access_executes_and_records_violation(tmp_path: Path) -> None:
    context = make_data_context(tmp_path, identity=Identity.ARC)
    result = json.loads(
        ProjectDataTools(context).query_project_csv(
            "Cost.csv",
            "Code",
            "A1",
        )
    )

    assert result["matched_count"] == 1
    events = storage.list_audit_events(
        context.db_path,
        context.project_id,
        context.conversation_id,
    )
    assert events[0]["boundary_violation"] == 1


def test_csv_mapping_respects_acting_discipline_permission(tmp_path: Path) -> None:
    context = replace(
        make_data_context(tmp_path),
        user_identity=Identity.ARC,
    )

    with pytest.raises(PermissionError, match="ARC users may map"):
        ProjectDataTools(context).analyze_ifc_csv_mapping(
            "Cost.csv",
            "MEP.ifc",
            "Code",
        )
