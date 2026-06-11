"""Deterministic context assembly for the Phase 1 pipeline.

Consumes the evidence the Smart Input Handler already gathered (including the
execution tracer's variable snapshots) and adds tree-sitter AST extraction. It
does NOT execute user code — execution happens exactly once, in the handler.
"""
from __future__ import annotations

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
    function_signature: str
    imports: list[str]
    function_source: str


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
            function_signature=ast_context.function_signature,
            imports=ast_context.imports,
            runtime_trace=trace,
            language=processed.language,
            full_code=processed.code,
            function_source=ast_context.function_source,
        )

    def _extract_ast(self, code: str, error_line: int) -> AstContext:
        encoded = code.encode("utf8")
        tree = self._parser.parse(encoded)
        lines = code.splitlines()
        target_row = _bounded_target_row(error_line, len(lines))

        func_node = _find_enclosing_function(tree.root_node, target_row)
        return AstContext(
            error_node=_line_window(lines, target_row),
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


def _bounded_target_row(error_line: int, line_count: int) -> int:
    if line_count <= 0:
        return 0
    return max(0, min(error_line - 1, line_count - 1))


def _node_text(encoded: bytes, start_byte: int, end_byte: int) -> str:
    return encoded[start_byte:end_byte].decode("utf8", errors="replace")


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
