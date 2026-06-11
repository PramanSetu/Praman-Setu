"""Deterministic context assembly for the Phase 1 pipeline.

Consumes the evidence the Smart Input Handler already gathered (including the
execution tracer's variable snapshots) and adds tree-sitter AST extraction. It
does NOT execute user code — execution happens exactly once, in the handler.
"""
from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Tree

from backend.orchestrator.state import ContextPackage, ProcessedInput


ERROR_WINDOW_LINES = 10
MODULE_LEVEL = "<module-level>"


@dataclass(frozen=True)
class AstContext:
    error_node: str
    error_window_with_lines: str
    function_signature: str
    imports: list[str]
    function_source: str
    enclosing_class: str | None
    enclosing_class_source: str | None
    callers: list[str]
    callees: list[str]
    constants: list[str]


class ContextBuilder:
    """Build the smallest useful evidence packet before any LLM call."""

    def __init__(self) -> None:
        self._language = Language(tspython.language())
        self._parser = Parser(self._language)

    async def build(self, processed: ProcessedInput) -> ContextPackage:
        trace = _runtime_trace(processed)
        error_line = processed.error_line or 1
        ast_context = await asyncio.to_thread(self._extract_ast, processed.code, error_line)

        return ContextPackage(
            error_node=ast_context.error_node,
            error_line=processed.error_line,
            error_window_with_lines=ast_context.error_window_with_lines,
            function_signature=ast_context.function_signature,
            imports=ast_context.imports,
            runtime_trace=trace,
            language=processed.language,
            enclosing_class=ast_context.enclosing_class,
            enclosing_class_source=ast_context.enclosing_class_source,
            callers=ast_context.callers,
            callees=ast_context.callees,
            constants=ast_context.constants,
            full_code=processed.code,
            function_source=ast_context.function_source,
        )

    def _extract_ast(self, code: str, error_line: int) -> AstContext:
        encoded = code.encode("utf8")
        tree = self._parser.parse(encoded)
        lines = code.splitlines()
        target_row = _bounded_target_row(error_line, len(lines))

        func_node = _find_enclosing_function(tree.root_node, target_row)
        enriched = _extract_python_ast_enrichment(code, target_row)
        return AstContext(
            error_node=_line_window(lines, target_row),
            error_window_with_lines=_line_window_with_numbers(lines, target_row),
            function_signature=self._function_signature(func_node, encoded, lines, target_row),
            imports=self._top_level_imports(tree, encoded),
            # Full enclosing function source so the Validator can splice the patch
            # back into the module. Falls back to the whole module when the error is
            # module-level (no enclosing function).
            function_source=(
                _node_text(encoded, func_node.start_byte, func_node.end_byte)
                if func_node is not None
                else code
            ),
            enclosing_class=enriched.enclosing_class,
            enclosing_class_source=enriched.enclosing_class_source,
            callers=enriched.callers,
            callees=enriched.callees,
            constants=enriched.constants,
        )

    def _function_signature(
        self,
        func_node: Node | None,
        encoded: bytes,
        lines: list[str],
        target_row: int,
    ) -> str:
        if func_node is None:
            return _nearest_preceding_function_signature(lines, target_row)

        block_node = _first_child_of_type(func_node, {"block", "suite"})
        if block_node is None:
            return lines[func_node.start_point[0]].strip()

        return _node_text(encoded, func_node.start_byte, block_node.start_byte).strip()

    def _top_level_imports(self, tree: Tree, encoded: bytes) -> list[str]:
        imports: list[str] = []
        for child in tree.root_node.children:
            if child.type in {"import_statement", "import_from_statement"}:
                imports.append(_node_text(encoded, child.start_byte, child.end_byte).strip())
        return imports


def _find_enclosing_function(node: Node, target_row: int) -> Node | None:
    found: Node | None = None
    if node.type == "function_definition" and node.start_point[0] <= target_row <= node.end_point[0]:
        found = node

    for child in node.children:
        child_match = _find_enclosing_function(child, target_row)
        if child_match is not None:
            found = child_match

    return found


def _first_child_of_type(node: Node, types: set[str]) -> Node | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _nearest_preceding_function_signature(lines: list[str], target_row: int) -> str:
    for index in range(min(target_row, len(lines) - 1), -1, -1):
        stripped = lines[index].strip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            return stripped
    return MODULE_LEVEL


def _line_window(lines: list[str], target_row: int) -> str:
    if not lines:
        return ""

    before = ERROR_WINDOW_LINES // 2
    start = max(0, target_row - before)
    end = min(len(lines), start + ERROR_WINDOW_LINES)
    start = max(0, end - ERROR_WINDOW_LINES)
    return "\n".join(lines[start:end])


def _line_window_with_numbers(lines: list[str], target_row: int) -> str:
    if not lines:
        return ""

    before = ERROR_WINDOW_LINES // 2
    start = max(0, target_row - before)
    end = min(len(lines), start + ERROR_WINDOW_LINES)
    start = max(0, end - ERROR_WINDOW_LINES)
    width = len(str(end))
    return "\n".join(
        f"{line_no:>{width}} | {lines[line_no - 1]}" for line_no in range(start + 1, end + 1)
    )


def _bounded_target_row(error_line: int, line_count: int) -> int:
    if line_count <= 0:
        return 0
    return max(0, min(error_line - 1, line_count - 1))


def _node_text(encoded: bytes, start_byte: int, end_byte: int) -> str:
    return encoded[start_byte:end_byte].decode("utf8", errors="replace")


@dataclass(frozen=True)
class PythonAstEnrichment:
    enclosing_class: str | None
    enclosing_class_source: str | None
    callers: list[str]
    callees: list[str]
    constants: list[str]


def _extract_python_ast_enrichment(code: str, target_row: int) -> PythonAstEnrichment:
    """Best-effort same-file context for valid Python modules.

    Tree-sitter keeps the basic context working for broken code. This stdlib AST
    enrichment adds semantic same-file relationships when the module can be
    parsed normally.
    """
    try:
        module = ast.parse(code)
    except SyntaxError:
        return PythonAstEnrichment(None, None, [], [], [])

    lines = code.splitlines()
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(module):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    target_func = _enclosing_ast_function(module, target_row + 1)
    target_name = target_func.name if target_func is not None else None
    enclosing_class_node = _enclosing_ast_class(target_func, parent) if target_func else None
    enclosing_class = _class_header_and_fields(lines, enclosing_class_node) if enclosing_class_node else None
    enclosing_class_source = _node_source(lines, enclosing_class_node) if enclosing_class_node else None

    functions = {
        node.name: node
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    call_names_by_function = {
        name: _called_function_names(node) for name, node in functions.items()
    }

    callees: list[str] = []
    if target_name:
        for callee_name in sorted(call_names_by_function.get(target_name, set())):
            callee_node = functions.get(callee_name)
            if callee_node is not None:
                callees.append(_node_source(lines, callee_node))

    callers: list[str] = []
    if target_name:
        for caller_name, call_names in sorted(call_names_by_function.items()):
            if caller_name != target_name and target_name in call_names:
                caller_node = functions.get(caller_name)
                if caller_node is not None:
                    callers.append(_node_source(lines, caller_node))

    return PythonAstEnrichment(
        enclosing_class=enclosing_class,
        enclosing_class_source=enclosing_class_source,
        callers=_cap_context_items(callers),
        callees=_cap_context_items(callees),
        constants=_top_level_constants(module, lines),
    )


def _enclosing_ast_function(
    module: ast.Module,
    line_no: int,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches = [
        node
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.lineno <= line_no <= (getattr(node, "end_lineno", node.lineno) or node.lineno)
    ]
    if not matches:
        return None
    return max(matches, key=lambda node: node.lineno)


def _enclosing_ast_class(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    parent: dict[ast.AST, ast.AST],
) -> ast.ClassDef | None:
    current: ast.AST | None = func_node
    while current in parent:
        current = parent[current]
        if isinstance(current, ast.ClassDef):
            return current
    return None


def _class_header_and_fields(lines: list[str], class_node: ast.ClassDef) -> str:
    """Return compact class context without duplicating every method body."""
    header = lines[class_node.lineno - 1].strip()
    members: list[str] = []
    for child in class_node.body:
        if isinstance(child, (ast.AnnAssign, ast.Assign)):
            members.append(_node_source(lines, child).strip())
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            members.append(lines[child.lineno - 1].strip())
    return "\n".join([header, *members])


def _called_function_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                names.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                names.add(child.func.attr)
    return names


def _top_level_constants(module: ast.Module, lines: list[str]) -> list[str]:
    constants: list[str] = []
    for node in module.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if names and all(name.isupper() for name in names):
                constants.append(_node_source(lines, node).strip())
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.isupper():
                constants.append(_node_source(lines, node).strip())
    return _cap_context_items(constants, max_items=8)


def _node_source(lines: list[str], node: ast.AST) -> str:
    end_lineno = getattr(node, "end_lineno", None)
    if end_lineno is None:
        return lines[node.lineno - 1].strip()
    return "\n".join(lines[node.lineno - 1 : end_lineno])


def _cap_context_items(items: list[str], *, max_items: int = 4, max_chars: int = 1200) -> list[str]:
    capped: list[str] = []
    for item in items[:max_items]:
        capped.append(item if len(item) <= max_chars else item[:max_chars].rstrip() + "\n...")
    return capped


def _runtime_trace(processed: ProcessedInput) -> dict:
    """Assemble the Diagnoser-facing trace from the handler's evidence.

    Single source of truth: error fields come from the handler's parse, the
    variable snapshots from the execution tracer. No re-execution.
    """
    return {
        "error_type": processed.error_type,
        "error_message": _message_only(processed.error_message, processed.error_type),
        "error_line": processed.error_line,
        "raw_stderr": processed.raw_stderr,
        "captured_variables": processed.captured_variables,
        "crash_locals": processed.crash_locals,
        "snapshots": processed.trace_snapshots,
    }


def _message_only(error_message: str, error_type: str | None) -> str:
    """Strip a leading ``ExceptionType: `` prefix, leaving just the message."""
    if error_type and error_message.startswith(f"{error_type}:"):
        return error_message[len(error_type) + 1 :].strip()
    return error_message


context_builder = ContextBuilder()
