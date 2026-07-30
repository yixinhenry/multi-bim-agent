from __future__ import annotations

import traceback
from typing import Any
from uuid import uuid4


def exception_diagnostic(exc: BaseException) -> dict[str, Any]:
    """Create a useful, bounded diagnostic without exposing environment secrets."""
    diagnostic_id = uuid4().hex[:12]
    exception_type = f"{type(exc).__module__}.{type(exc).__name__}"
    message = str(exc).strip()
    representation = repr(exc)
    chain = []
    current = exc.__cause__ or exc.__context__
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < 5:
        seen.add(id(current))
        chain.append(
            {
                "type": f"{type(current).__module__}.{type(current).__name__}",
                "message": str(current).strip(),
                "repr": repr(current)[:2000],
            }
        )
        current = current.__cause__ or current.__context__
    trace = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )[-12000:]
    return {
        "diagnostic_id": diagnostic_id,
        "exception_type": exception_type,
        "message": message or "(empty exception message)",
        "repr": representation[:4000],
        "cause_chain": chain,
        "traceback": trace,
    }


def diagnostic_markdown(diagnostic: dict[str, Any]) -> str:
    lines = [
        f"**Diagnostic ID:** `{diagnostic['diagnostic_id']}`",
        f"**Exception type:** `{diagnostic['exception_type']}`",
        f"**Message:** `{diagnostic['message']}`",
        f"**Representation:** `{diagnostic['repr']}`",
    ]
    if diagnostic["cause_chain"]:
        lines.append("**Cause chain:**")
        for cause in diagnostic["cause_chain"]:
            lines.append(
                f"- `{cause['type']}` — `{cause['message'] or cause['repr']}`"
            )
    lines.extend(
        [
            "",
            "<details><summary>Traceback</summary>",
            "",
            "```text",
            diagnostic["traceback"],
            "```",
            "</details>",
        ]
    )
    return "\n".join(lines)
