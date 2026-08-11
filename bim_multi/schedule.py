from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


REQUIRED_COLUMNS = frozenset(
    {"Task", "PlannedStart", "PlannedFinish", "Status", "Progress"}
)


@dataclass(frozen=True)
class ScheduleTask:
    discipline: str
    name: str
    planned_start: date
    planned_finish: date
    status: str
    progress: float


@dataclass(frozen=True)
class ScheduleSummary:
    tasks: tuple[ScheduleTask, ...]
    overall_progress: float
    planned_start: date
    planned_finish: date
    completed_tasks: int


def load_schedule(path: Path) -> ScheduleSummary:
    rows = _read_rows(path)
    if not rows:
        raise ValueError("Schedule.csv has no task rows")

    tasks = []
    for row_number, row in enumerate(rows, start=2):
        name = row["Task"].strip()
        if not name:
            raise ValueError(f"Schedule.csv row {row_number} has an empty Task")
        try:
            planned_start = date.fromisoformat(row["PlannedStart"].strip())
            planned_finish = date.fromisoformat(row["PlannedFinish"].strip())
        except ValueError as exc:
            raise ValueError(
                f"Schedule.csv row {row_number} contains a non-ISO date"
            ) from exc
        if planned_finish < planned_start:
            raise ValueError(
                f"Schedule.csv row {row_number} finishes before it starts"
            )
        try:
            progress = float(row["Progress"].strip().removesuffix("%"))
        except ValueError as exc:
            raise ValueError(
                f"Schedule.csv row {row_number} has invalid Progress"
            ) from exc
        if not 0 <= progress <= 100:
            raise ValueError(
                f"Schedule.csv row {row_number} Progress must be between 0 and 100"
            )
        tasks.append(
            ScheduleTask(
                discipline=row.get("Discipline", "").strip(),
                name=name,
                planned_start=planned_start,
                planned_finish=planned_finish,
                status=row["Status"].strip() or "Unknown",
                progress=progress,
            )
        )

    return ScheduleSummary(
        tasks=tuple(tasks),
        overall_progress=sum(task.progress for task in tasks) / len(tasks),
        planned_start=min(task.planned_start for task in tasks),
        planned_finish=max(task.planned_finish for task in tasks),
        completed_tasks=sum(task.progress >= 100 for task in tasks),
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    last_error = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                columns = set(reader.fieldnames or [])
                missing = sorted(REQUIRED_COLUMNS - columns)
                if missing:
                    raise ValueError(
                        "Schedule.csv is missing required columns: "
                        + ", ".join(missing)
                    )
                return [
                    {
                        str(key): "" if value is None else str(value)
                        for key, value in row.items()
                    }
                    for row in reader
                ]
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"Unable to decode Schedule.csv: {last_error}")
