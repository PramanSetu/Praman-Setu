"""Deterministic edit application for one-file repair.

Two strategies live here:

  apply_exact_edits  — legacy string search/replace (kept for the unit test and
                       as a last-resort fallback). Brittle: an ``old`` block that
                       doesn't match the source verbatim is dropped.

  apply_unit_rewrites — the primary path. The agent returns whole corrected
                       *units* (a top-level function/class by name, the trailing
                       module-level block as ``<module>``, or the entire file as
                       ``<file>``). We locate each unit via the AST and splice the
                       replacement in, compile-checking after every unit so a
                       broken rewrite is skipped instead of corrupting the file.
                       This removes both string-match brittleness and the
                       indentation-corruption failure mode.
"""
from __future__ import annotations

import ast

from pydantic import BaseModel, Field


class CodeEdit(BaseModel):
    old: str = Field(min_length=1)
    new: str
    reason: str = ""


class UnitRewrite(BaseModel):
    """A whole-unit replacement.

    ``target`` is one of:
      * a top-level function or class name (e.g. ``"summarize"``)
      * ``"<module>"`` — the contiguous trailing block of top-level executable
        statements (e.g. the ``if __name__ == "__main__":`` section)
      * ``"<file>"`` — replace the entire file (required when the current code has
        a SyntaxError and therefore cannot be parsed for unit-level splicing)
    """

    target: str = Field(min_length=1)
    new_source: str = Field(min_length=1)
    reason: str = ""


class ApplyResult(BaseModel):
    applied_code: str
    applied_count: int
    failures: list[str] = Field(default_factory=list)


# Aliases the agent may use for the module-level block.
_MODULE_TARGETS = {"<module>", "__main__", "__module__", "module", "main"}


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


def _compiles(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def _named_units(tree: ast.Module) -> dict[str, tuple[int, int]]:
    """Map top-level function/class name -> (start_line, end_line), 1-based inclusive."""
    units: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            end = node.end_lineno or start
            units[node.name] = (start, end)
    return units


def _module_span(tree: ast.Module) -> tuple[int, int] | None:
    """Line span of the contiguous *trailing* run of top-level executable code.

    Stops at the first def/class/import scanning from the bottom, so it captures
    the typical ``if __name__ == "__main__":`` block without ever overlapping a
    function or class body.
    """
    trailing: list[ast.stmt] = []
    for node in reversed(tree.body):
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom),
        ):
            break
        trailing.append(node)
    if not trailing:
        return None
    trailing.reverse()
    start = trailing[0].lineno
    end = trailing[-1].end_lineno or start
    return start, end


def _splice(code: str, start: int, end: int, new_source: str) -> str:
    """Replace lines [start, end] (1-based inclusive) with ``new_source``."""
    lines = code.splitlines(keepends=True)
    block = new_source if new_source.endswith("\n") else new_source + "\n"
    return "".join(lines[: start - 1] + [block] + lines[end:])


def apply_unit_rewrites(code: str, units: list[UnitRewrite]) -> ApplyResult:
    """Apply whole-unit rewrites one at a time, compile-checking after each.

    A unit whose target can't be located, or whose rewrite would stop the file
    compiling, is skipped and recorded in ``failures`` — the good units still land.
    """
    current = code
    failures: list[str] = []
    applied = 0

    for index, unit in enumerate(units, start=1):
        # Whole-file replacement — the only option when the current code doesn't
        # parse (e.g. an unfixed SyntaxError), and a valid escape hatch otherwise.
        if unit.target == "<file>":
            candidate = unit.new_source
            if not _compiles(candidate):
                failures.append(f"unit {index} (<file>): rewrite does not compile — skipped")
                continue
            current = candidate
            applied += 1
            continue

        try:
            tree = ast.parse(current)
        except SyntaxError as exc:
            failures.append(
                f"unit {index} ('{unit.target}'): current code has a SyntaxError "
                f"({exc.msg}) — return a single '<file>' unit to fix it first"
            )
            break

        named = _named_units(tree)
        if unit.target in named:
            start, end = named[unit.target]
        elif unit.target in _MODULE_TARGETS:
            span = _module_span(tree)
            if span is None:
                failures.append(f"unit {index} ('{unit.target}'): no module-level block to replace")
                continue
            start, end = span
        else:
            failures.append(
                f"unit {index}: target '{unit.target}' is not a top-level function/class "
                f"(have: {', '.join(named) or 'none'})"
            )
            continue

        candidate = _splice(current, start, end, unit.new_source)
        if not _compiles(candidate):
            failures.append(
                f"unit {index} ('{unit.target}'): rewrite does not compile in context — skipped"
            )
            continue
        current = candidate
        applied += 1

    return ApplyResult(applied_code=current, applied_count=applied, failures=failures)
