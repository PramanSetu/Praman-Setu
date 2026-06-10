"""Deterministic error extraction and Phase 2 optimization signals."""
from __future__ import annotations

import re

FAST_PATH_ERROR_TYPES = {"NameError", "SyntaxError"}
TRACEBACK_ERROR_RE = re.compile(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)):\s*(.*)$")
TRACEBACK_LINE_RE = re.compile(r'(?m)^\s*File ".*?", line (\d+)')


def is_fast_path_eligible(error_type: str | None, line_count: int) -> bool:
    """Return a metadata flag only; Phase 1 still sends every case to Diagnoser."""
    return bool(error_type in FAST_PATH_ERROR_TYPES and line_count < 50)


def extract_exception_line(error_message: str) -> str:
    matches = TRACEBACK_ERROR_RE.findall(error_message)
    if not matches:
        return error_message.strip()
    error_type, detail = matches[-1]
    return f"{error_type}: {detail}".rstrip()


def extract_error_type(error_message: str) -> str | None:
    matches = TRACEBACK_ERROR_RE.findall(error_message)
    if not matches:
        return None
    return matches[-1][0]


def extract_error_line(error_message: str) -> int | None:
    matches = TRACEBACK_LINE_RE.findall(error_message)
    if not matches:
        return None
    return int(matches[-1])
