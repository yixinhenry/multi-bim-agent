from __future__ import annotations

from bim_multi.diagnostics import diagnostic_markdown, exception_diagnostic


class EmptyFailure(Exception):
    pass


def test_empty_exception_still_has_actionable_diagnostic() -> None:
    try:
        raise EmptyFailure()
    except EmptyFailure as exc:
        diagnostic = exception_diagnostic(exc)
    assert diagnostic["exception_type"].endswith(".EmptyFailure")
    assert diagnostic["message"] == "(empty exception message)"
    assert "EmptyFailure()" in diagnostic["repr"]
    assert "raise EmptyFailure()" in diagnostic["traceback"]
    rendered = diagnostic_markdown(diagnostic)
    assert diagnostic["diagnostic_id"] in rendered
    assert "Traceback" in rendered


def test_exception_cause_chain_is_included() -> None:
    try:
        try:
            raise TimeoutError()
        except TimeoutError as cause:
            raise RuntimeError("Model request failed") from cause
    except RuntimeError as exc:
        diagnostic = exception_diagnostic(exc)
    assert diagnostic["cause_chain"][0]["type"] == "builtins.TimeoutError"
    assert diagnostic["cause_chain"][0]["message"] == ""
