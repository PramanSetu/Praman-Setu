"""AST-based test module constructor for PatchMind's Validator Gate 4.

Replaces the naive ``_strip_top_level_calls`` with a principled, AST-aware
reconstruction that makes the patched module safe to import during pytest
collection — regardless of how the original code was structured.

Core philosophy
───────────────
  KEEP   — anything that defines structure but does NOT execute logic on import.
  STRIP  — anything that executes logic, performs I/O, or calls functions at
            module level.
  RECONSTRUCT — produce a clean AST from the safe nodes, unparse to source,
            and append the generated test.

Public surface
──────────────
  reconstruct_safe_module(source: str) -> str
      Takes a patched module source string and returns a version that is safe
      to import.  Falls back to the original source on SyntaxError so Gate 1
      can still report the problem.

  build_test_module(patched_module: str, generated_test: str) -> str
      Full pipeline: reconstruct the module, strip local self-imports from the
      test, ensure ``import pytest`` is present, concatenate.  Replaces the
      old ``_strip_top_level_calls``-based implementation in validator.py.
"""
from __future__ import annotations

import ast
from typing import Sequence

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reconstruct_safe_module(source: str) -> str:
    """Return a version of ``source`` that is safe to import during pytest collection.

    Parses the module, keeps only import-safe top-level statements, and unparses
    to a clean source string.  On ``SyntaxError`` the original source is returned
    unchanged so Gate 1 can detect and report the syntax problem.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    safe_body: list[ast.stmt] = []
    for index, node in enumerate(tree.body):
        if _is_safe_module_node(node, index):
            safe_body.append(node)

    new_tree = ast.Module(body=safe_body, type_ignores=[])
    ast.fix_missing_locations(new_tree)
    return ast.unparse(new_tree)


def build_test_module(patched_module: str, generated_test: str) -> str:
    """Construct the source string that pytest will import and run.

    Steps:
    1. Reconstruct the patched module — strips all top-level execution, keeps
       definitions and safe constant assignments.
    2. Strip any self-imports from the generated test (e.g. ``from user_code
       import ...`` that the LLM emits but that are unresolvable in the sandbox).
    3. Ensure ``import pytest`` is present when the test uses ``pytest.raises``.
    4. Concatenate the clean module and the prepared test.
    """
    safe_module = reconstruct_safe_module(patched_module)
    test = _ensure_pytest_import(_strip_local_imports(generated_test))
    return safe_module + "\n\n" + test


# ---------------------------------------------------------------------------
# Keep / strip classification
# ---------------------------------------------------------------------------

def _is_safe_module_node(node: ast.stmt, index: int) -> bool:
    """Return True if ``node`` can safely appear in a module that is imported.

    Classification follows the KEEP/STRIP spec:

    KEEP unconditionally:
      Import, ImportFrom, FunctionDef, AsyncFunctionDef, ClassDef, Pass

    KEEP conditionally:
      Assign              — only when the RHS is a safe literal (no calls)
      AnnAssign           — only when there is no value (type-hint only)
      Expr[Constant(str)] — only at position 0 (module docstring)

    STRIP:
      Everything else — If (including __name__ == "__main__"), For, While,
      With, Try, Assert, Delete, Match, Expr[non-literal], Assign[non-literal],
      AnnAssign[with value], Global, Nonlocal, Raise, Return.
    """
    # --- Unconditional keeps ---
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return True

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return True

    if isinstance(node, ast.Pass):
        return True

    # --- Module-level docstring (first statement, string constant) ---
    if (
        index == 0
        and isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        return True

    # --- Assign: keep only when the whole RHS is a safe literal ---
    if isinstance(node, ast.Assign):
        return _is_safe_literal(node.value)

    # --- AnnAssign: keep type-hint-only stmts (``x: int``) but not ``x: int = f()`` ---
    if isinstance(node, ast.AnnAssign):
        return node.value is None

    # --- Everything else executes on import → strip ---
    return False


# ---------------------------------------------------------------------------
# Safe-literal check (recursive)
# ---------------------------------------------------------------------------

def _is_safe_literal(node: ast.expr) -> bool:
    """Return True iff ``node`` is a compile-time constant — zero execution risk.

    Safe:
      - ast.Constant   (int, float, str, bytes, bool, None, Ellipsis)
      - ast.List, ast.Tuple, ast.Set  where ALL elements are safe
      - ast.Dict where ALL keys and values are safe (None keys are spread operators)

    Everything else (ast.Call, ast.BinOp, ast.Name, ast.Attribute, …) is unsafe.
    """
    if isinstance(node, ast.Constant):
        return True

    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_safe_literal(elt) for elt in node.elts)

    if isinstance(node, ast.Dict):
        return all(
            # None key = dict unpacking (**other_dict) — treat as unsafe
            k is not None and _is_safe_literal(k) and _is_safe_literal(v)
            for k, v in zip(node.keys, node.values)
        )

    return False


# ---------------------------------------------------------------------------
# Test-code helpers (carried over from validator.py; now the canonical location)
# ---------------------------------------------------------------------------

# The tracer runs user code under this virtual filename, so the LLM-generated
# test often writes ``from user_code import ...``.  That import is both
# redundant (the function is inlined) and unresolvable in the sandbox.
_LOCAL_MODULES: frozenset[str] = frozenset({"user_code", "main", "solution", "snippet"})


def _strip_local_imports(code: str) -> str:
    """Drop imports that try to import from the module under test itself."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    body = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in _LOCAL_MODULES:
            continue
        if isinstance(node, ast.Import) and any(a.name in _LOCAL_MODULES for a in node.names):
            continue
        body.append(node)

    tree.body = body
    return ast.unparse(tree)


def _ensure_pytest_import(code: str) -> str:
    """Prepend ``import pytest`` when the test uses it but forgot to import it.

    The LLM frequently writes ``pytest.raises(...)`` without ``import pytest``,
    which fails at runtime with NameError.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    uses_pytest = any(isinstance(n, ast.Name) and n.id == "pytest" for n in ast.walk(tree))
    has_import = any(
        isinstance(n, ast.Import) and any(a.name == "pytest" for a in n.names)
        for n in ast.walk(tree)
    )
    if uses_pytest and not has_import:
        return "import pytest\n" + code
    return code
