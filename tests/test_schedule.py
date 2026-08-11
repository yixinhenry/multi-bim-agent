from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from bim_multi.schedule import load_schedule


def test_load_schedule_builds_project_progress_summary(tmp_path: Path) -> None:
    path = tmp_path / "Schedule.csv"
    path.write_text(
        "Task,Discipline,PlannedStart,PlannedFinish,Status,Progress\n"
        "Foundations,STR,2026-08-01,2026-08-05,Completed,100\n"
        "Walls,ARC,2026-08-06,2026-08-10,In Progress,50\n"
        "Ducts,MEP,2026-08-09,2026-08-16,Not Started,0\n",
        encoding="utf-8",
    )

    summary = load_schedule(path)

    assert summary.overall_progress == 50
    assert summary.planned_start == date(2026, 8, 1)
    assert summary.planned_finish == date(2026, 8, 16)
    assert summary.completed_tasks == 1
    assert [task.name for task in summary.tasks] == [
        "Foundations",
        "Walls",
        "Ducts",
    ]


def test_load_schedule_rejects_missing_required_columns(tmp_path: Path) -> None:
    path = tmp_path / "Schedule.csv"
    path.write_text("Task,Progress\nWalls,50\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        load_schedule(path)
