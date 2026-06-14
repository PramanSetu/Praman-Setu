"""Deterministic neutralization of non-terminating top-level code.

Some files start worker threads/processes at import time with non-daemon workers
that loop forever, so the program never exits and can't be run or validated
headlessly. This transform makes those workers ``daemon=True`` so the process can
terminate (daemons are killed when the main thread exits) — turning an infinite
hang into a normal, validatable run while preserving behaviour during execution.

It edits only the ``daemon`` keyword via AST source positions, so all other
formatting and comments are preserved (no full reformat).
"""
from __future__ import annotations

import ast

_THREAD_CTORS = {"Thread", "Process"}


def _is_thread_ctor(func: ast.expr) -> bool:
    if isinstance(func, ast.Attribute):
        return func.attr in _THREAD_CTORS
    if isinstance(func, ast.Name):
        return func.id in _THREAD_CTORS
    return False


def neutralize_nontermination(code: str) -> tuple[str, list[str]]:
    """Add ``daemon=True`` to Thread/Process constructors that lack it.

    Returns (possibly_rewritten_code, notes). If nothing changed (no such
    constructors, or all already daemon), the original code and an empty notes
    list are returned.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, []

    targets: list[tuple[int, int, bool]] = []  # (end_lineno, end_col_offset, has_args)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and _is_thread_ctor(node.func)
            and not any(kw.arg == "daemon" for kw in node.keywords)
            and node.end_lineno is not None
            and node.end_col_offset is not None
        ):
            targets.append((node.end_lineno, node.end_col_offset, bool(node.args or node.keywords)))

    if not targets:
        return code, []

    lines = code.splitlines(keepends=True)
    # Insert from the last position backwards so earlier offsets stay valid.
    for end_lineno, end_col, has_args in sorted(targets, reverse=True):
        insert = ", daemon=True" if has_args else "daemon=True"
        idx = end_lineno - 1
        line = lines[idx]
        pos = end_col - 1  # end_col is just past the closing ')'
        lines[idx] = line[:pos] + insert + line[pos:]

    note = (
        f"made {len(targets)} background thread/process start(s) daemon=True so the program "
        f"can terminate and be validated — confirm this matches your intent"
    )
    return "".join(lines), [note]
