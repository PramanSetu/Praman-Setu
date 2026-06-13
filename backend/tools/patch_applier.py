"""Deterministic exact-edit application for one-file repair."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CodeEdit(BaseModel):
    old: str = Field(min_length=1)
    new: str
    reason: str = ""


class ApplyResult(BaseModel):
    applied_code: str
    applied_count: int
    failures: list[str] = Field(default_factory=list)


def apply_exact_edits(code: str, edits: list[CodeEdit]) -> ApplyResult:
    current = code
    failures: list[str] = []
    applied = 0

    for index, edit in enumerate(edits, start=1):
        count = current.count(edit.old)
        if count == 0:
            failures.append(f"edit {index}: old block not found")
            continue
        if count > 1:
            failures.append(f"edit {index}: old block matched {count} locations")
            continue
        current = current.replace(edit.old, edit.new, 1)
        applied += 1

    return ApplyResult(applied_code=current, applied_count=applied, failures=failures)
