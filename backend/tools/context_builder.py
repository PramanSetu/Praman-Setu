"""Deterministic context assembly for the Phase 1 pipeline."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Tree

from backend.orchestrator.state import ContextPackage, ProcessedInput
from backend.tools.sandbox.executor import SandboxResult
from backend.tools.sandbox.pool import sandbox_pool


ERROR_WINDOW_LINES = 10
MODULE_LEVEL = "<module-level>"


@dataclass(frozen=True)
class AstContext:
    error_node: str
    function_signature: str
    imports: list[str]


class SandboxExecutor(Protocol):
    async def execute(
        self,
        language: str,
        code: str,
        cmd: list[str] | None = None,
        timeout: int | None = None,
    ) -> SandboxResult: ...


class ContextBuilder:
    """Build the smallest useful evidence packet before any LLM call."""

    def __init__(self, sandbox: SandboxExecutor = sandbox_pool) -> None:
        self.sandbox = sandbox
        self._language = Language(tspython.language())
        self._parser = Parser(self._language)

    async def build(self, processed: ProcessedInput) -> ContextPackage:
        trace = await self._get_runtime_trace(processed.code, processed.language)
        error_line = trace.get("error_line") or processed.error_line or 1
        ast_context = await asyncio.to_thread(self._extract_ast, processed.code, error_line)

        return ContextPackage(
            error_node=ast_context.error_node,
            function_signature=ast_context.function_signature,
            imports=ast_context.imports,
            runtime_trace=trace,
            language=processed.language,
        )

    async def _get_runtime_trace(self, code: str, language: str = "python") -> dict:
        result = await self.sandbox.execute(language, code)
        stderr = result.stderr or ""

        error_type = "Unknown"
        error_message = ""
        lines = stderr.strip().splitlines()
        if lines:
            match = re.match(r"^(\w+):\s*(.*)$", lines[-1].strip())
            if match:
                error_type, error_message = match.groups()

        line_matches = re.findall(r'File ".*?", line (\d+)', stderr)
        if not line_matches:
            line_matches = re.findall(r"line (\d+)", stderr)
        error_line = int(line_matches[-1]) if line_matches else None

        return {
            "error_type": error_type,
            "error_message": error_message,
            "error_line": error_line,
            "raw_stderr": stderr,
        }

    def _extract_ast(self, code: str, error_line: int) -> AstContext:
        encoded = code.encode("utf8")
        tree = self._parser.parse(encoded)
        lines = code.splitlines()
        target_row = _bounded_target_row(error_line, len(lines))

        return AstContext(
            error_node=_line_window(lines, target_row),
            function_signature=self._function_signature(tree, encoded, lines, target_row),
            imports=self._top_level_imports(tree, encoded),
        )

    def _function_signature(
        self,
        tree: Tree,
        encoded: bytes,
        lines: list[str],
        target_row: int,
    ) -> str:
        func_node = _find_enclosing_function(tree.root_node, target_row)
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


context_builder = ContextBuilder()
