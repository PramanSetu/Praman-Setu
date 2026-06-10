"""Deterministic Python-only language detection."""
from __future__ import annotations

import ast
from pathlib import PurePath

from backend.input_handler.models import DetectionMethod, LanguageDetection


class UnsupportedLanguageError(ValueError):
    """Raised when input is clearly not supported by the Python-only MVP."""


PYTHON_EXTENSIONS = {".py", ".pyw"}
KNOWN_NON_PYTHON_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".rb",
    ".rs",
    ".scala",
    ".swift",
    ".ts",
    ".tsx",
}

def detect_python_language(code: str, filename: str | None = None) -> LanguageDetection:
    """Detect Python inputs using cheap deterministic signals.

    Phase 1 accepts only Python. Clear non-Python file extensions fail closed.
    Unlabeled snippets are accepted only when Python's parser succeeds.
    """
    extension = _extension(filename)
    if extension in PYTHON_EXTENSIONS:
        return LanguageDetection(
            language="python",
            confidence=0.99,
            method=DetectionMethod.EXTENSION,
            reason=f"filename extension {extension!r} maps to Python",
        )
    if extension in KNOWN_NON_PYTHON_EXTENSIONS:
        raise UnsupportedLanguageError(
            f"unsupported language for extension {extension!r}; Phase 1 accepts Python only"
        )

    first_line = code.lstrip().splitlines()[0] if code.strip() else ""
    if first_line.startswith("#!"):
        if "python" in first_line.lower():
            return LanguageDetection(
                language="python",
                confidence=0.98,
                method=DetectionMethod.SHEBANG,
                reason="shebang references Python",
            )
        raise UnsupportedLanguageError("unsupported shebang; Phase 1 accepts Python only")

    if not is_python_by_ast(code):
        raise UnsupportedLanguageError(
            "unable to confidently detect Python; provide a .py filename or Python shebang"
        )

    return LanguageDetection(
        language="python",
        confidence=0.85,
        method=DetectionMethod.AST_PARSE,
        reason="snippet parsed successfully with Python ast",
    )


def is_python_by_ast(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False
    except Exception:
        return False


def _extension(filename: str | None) -> str:
    if not filename:
        return ""
    return PurePath(filename).suffix.lower()
