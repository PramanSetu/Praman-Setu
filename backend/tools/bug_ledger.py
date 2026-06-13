"""Deterministic whole-file bug ledger for pasted Python code.

The ledger is intentionally cheap and local: it does not call an LLM and it does
not execute user code. It gives the repair agent a whole-file map before the
first Groq call, so the model is not limited to the first runtime crash.
"""
from __future__ import annotations

import ast
import builtins
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.orchestrator.state import ProcessedInput


IssueKind = Literal[
    "syntax",
    "runtime",
    "undefined_name_hint",
    "top_level_input",
    "top_level_execution",
]


class LedgerIssue(BaseModel):
    kind: IssueKind
    line: int | None = None
    symbol: str | None = None
    message: str
    severity: Literal["error", "warning", "info"] = "info"


class SymbolInfo(BaseModel):
    name: str
    line: int


class BugLedger(BaseModel):
    code_compiles: bool
    issues: list[LedgerIssue] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    functions: list[SymbolInfo] = Field(default_factory=list)
    classes: list[SymbolInfo] = Field(default_factory=list)
    top_level_executable_lines: list[int] = Field(default_factory=list)
    top_level_input_lines: list[int] = Field(default_factory=list)
    runtime_error_type: str | None = None
    runtime_error_line: int | None = None
    runtime_error_message: str = ""
    crash_locals: dict[str, str] | None = None

    def prompt_summary(self) -> str:
        issue_lines = [
            f"- {issue.kind} line={issue.line}: {issue.message}"
            + (f" symbol={issue.symbol}" if issue.symbol else "")
            for issue in self.issues
        ]
        functions = ", ".join(f"{item.name}@{item.line}" for item in self.functions) or "<none>"
        classes = ", ".join(f"{item.name}@{item.line}" for item in self.classes) or "<none>"
        imports = "\n".join(self.imports) or "<none>"
        return (
            f"code_compiles: {self.code_compiles}\n"
            f"runtime_error: {self.runtime_error_type} at line {self.runtime_error_line}: "
            f"{self.runtime_error_message or '<none>'}\n"
            f"functions: {functions}\n"
            f"classes: {classes}\n"
            f"imports:\n{imports}\n"
            f"top_level_executable_lines: {self.top_level_executable_lines}\n"
            f"top_level_input_lines: {self.top_level_input_lines}\n"
            f"issues:\n" + ("\n".join(issue_lines) if issue_lines else "<none>")
        )


def build_bug_ledger(code: str, processed: ProcessedInput | None = None) -> BugLedger:
    issues: list[LedgerIssue] = []
    runtime_error_type = processed.error_type if processed else None
    runtime_error_line = processed.error_line if processed else None
    runtime_error_message = processed.error_message if processed else ""

    if processed and processed.error_type:
        issues.append(
            LedgerIssue(
                kind="runtime" if processed.error_type != "SyntaxError" else "syntax",
                line=processed.error_line,
                symbol=processed.error_type,
                message=processed.error_message or processed.raw_stderr or processed.error_type,
                severity="error",
            )
        )

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        if not any(issue.kind == "syntax" for issue in issues):
            issues.append(
                LedgerIssue(
                    kind="syntax",
                    line=exc.lineno,
                    message=exc.msg,
                    severity="error",
                )
            )
        return BugLedger(
            code_compiles=False,
            issues=issues,
            runtime_error_type=runtime_error_type or "SyntaxError",
            runtime_error_line=runtime_error_line or exc.lineno,
            runtime_error_message=runtime_error_message or exc.msg,
            crash_locals=processed.crash_locals if processed else None,
        )

    imports = _imports(tree, code)
    functions = [
        SymbolInfo(name=node.name, line=node.lineno)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    classes = [
        SymbolInfo(name=node.name, line=node.lineno)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    ]
    top_exec = _top_level_executable_lines(tree)
    top_input = _top_level_input_lines(tree)

    for line in top_input:
        issues.append(
            LedgerIssue(
                kind="top_level_input",
                line=line,
                message="top-level input() makes headless validation depend on synthetic stdin",
                severity="warning",
            )
        )
    for line in top_exec:
        issues.append(
            LedgerIssue(
                kind="top_level_execution",
                line=line,
                message="top-level executable statement can surface script-level crashes",
                severity="info",
            )
        )

    issues.extend(_undefined_name_hints(tree))

    return BugLedger(
        code_compiles=True,
        issues=issues,
        imports=imports,
        functions=functions,
        classes=classes,
        top_level_executable_lines=top_exec,
        top_level_input_lines=top_input,
        runtime_error_type=runtime_error_type,
        runtime_error_line=runtime_error_line,
        runtime_error_message=runtime_error_message,
        crash_locals=processed.crash_locals if processed else None,
    )


def _imports(tree: ast.Module, code: str) -> list[str]:
    lines = code.splitlines()
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(lines[node.lineno - 1].strip())
    return out


def _top_level_executable_lines(tree: ast.Module) -> list[int]:
    safe = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    out: list[int] = []
    for index, node in enumerate(tree.body):
        if index == 0 and _is_docstring(node):
            continue
        if not isinstance(node, safe):
            out.append(getattr(node, "lineno", 1))
    return out


def _top_level_input_lines(tree: ast.Module) -> list[int]:
    lines: list[int] = []
    for node in tree.body:
        for child in ast.walk(node):
            if _is_input_call(child):
                lines.append(getattr(child, "lineno", getattr(node, "lineno", 1)))
    return sorted(set(lines))


def _undefined_name_hints(tree: ast.Module) -> list[LedgerIssue]:
    module_defined = _module_defined_names(tree)
    builtin_names = set(dir(builtins))
    issues: list[LedgerIssue] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            known = module_defined | builtin_names | _function_defined_names(node)
            for loaded in _loaded_names(node):
                if loaded.name not in known:
                    issues.append(
                        LedgerIssue(
                            kind="undefined_name_hint",
                            line=loaded.line,
                            symbol=loaded.name,
                            message=f"name {loaded.name!r} is read but not defined in visible scope",
                            severity="warning",
                        )
                    )
    return _dedupe_undefined(issues)


def _module_defined_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.For, ast.With)):
            names.update(_assigned_names(node))
    return names


def _function_defined_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = {arg.arg for arg in func.args.args + func.args.posonlyargs + func.args.kwonlyargs}
    if func.args.vararg:
        names.add(func.args.vararg.arg)
    if func.args.kwarg:
        names.add(func.args.kwarg.arg)
    for node in ast.walk(func):
        names.update(_assigned_names(node))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _assigned_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    targets: list[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets.extend(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets.append(node.target)
    elif isinstance(node, ast.For):
        targets.append(node.target)
    elif isinstance(node, ast.With):
        targets.extend(item.optional_vars for item in node.items if item.optional_vars is not None)
    elif isinstance(node, ast.ExceptHandler) and node.name:
        names.add(node.name)

    for target in targets:
        for child in ast.walk(target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
    return names


class _LoadedName(BaseModel):
    name: str
    line: int


def _loaded_names(node: ast.AST) -> list[_LoadedName]:
    loaded: list[_LoadedName] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            loaded.append(_LoadedName(name=child.id, line=child.lineno))
    return loaded


def _dedupe_undefined(issues: list[LedgerIssue]) -> list[LedgerIssue]:
    seen: set[tuple[str | None, int | None]] = set()
    out: list[LedgerIssue] = []
    for issue in issues:
        key = (issue.symbol, issue.line)
        if key not in seen:
            seen.add(key)
            out.append(issue)
    return out


def _is_docstring(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_input_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "input"
    )
