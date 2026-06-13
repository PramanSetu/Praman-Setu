"""Deterministic Python-only language detection."""
from __future__ import annotations

import ast
import re
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

_PYTHON_TRACEBACK_RE = re.compile(
    r"(?m)(Traceback \(most recent call last\)|File \".*?\.py\", line \d+|"
    r"\b(?:SyntaxError|NameError|TypeError|ValueError|KeyError|IndexError|ZeroDivisionError):)"
)
_PYTHON_LIKE_RE = re.compile(
    r"(?m)^\s*(def|async\s+def|class|from\s+\w+\s+import|import\s+\w+|"
    r"if\s+__name__\s*==|for\s+\w+\s+in|while\s+.+:|try:|except\b|with\s+.+:|"
    r"print\s*\(|input\s*\()"
)


def detect_python_language(
    code: str,
    filename: str | None = None,
    error_message: str | None = None,
) -> LanguageDetection:
    """Detect Python inputs using cheap deterministic signals.

    Phase 1 accepts only Python. Clear non-Python file extensions fail closed.
    Unlabeled snippets are accepted when Python's parser succeeds, when the
    supplied error is clearly a Python traceback, or when the code is strongly
    Python-like. This keeps syntax-broken pasted Python inside the repair path.
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

    if _looks_obviously_non_python(code):
        raise UnsupportedLanguageError(
            "unable to confidently detect Python; snippet looks like a non-Python language"
        )

    if is_python_by_ast(code):
        return LanguageDetection(
            language="python",
            confidence=0.85,
            method=DetectionMethod.AST_PARSE,
            reason="snippet parsed successfully with Python ast",
        )

    if error_message and _PYTHON_TRACEBACK_RE.search(error_message):
        return LanguageDetection(
            language="python",
            confidence=0.78,
            method=DetectionMethod.TRACEBACK,
            reason="supplied error message looks like a Python traceback",
        )

    if _looks_like_python(code):
        return LanguageDetection(
            language="python",
            confidence=0.62,
            method=DetectionMethod.HEURISTIC,
            reason="unlabeled snippet contains Python-like syntax",
        )

    raise UnsupportedLanguageError(
        "unable to confidently detect Python; provide a .py filename, Python shebang, or Python traceback"
    )


def _looks_like_python(code: str) -> bool:
    if not _PYTHON_LIKE_RE.search(code):
        return False
    return not _looks_obviously_non_python(code)


def _looks_obviously_non_python(code: str) -> bool:
    lowered = code.lower()
    js_markers = ("console.log", "function ", "=>", "let ", "const ", "var ", "document.")
    return any(marker in lowered for marker in js_markers)


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
