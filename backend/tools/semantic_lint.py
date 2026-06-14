"""Deterministic semantic linters — AST detectors for logic anti-patterns that
do NOT crash, so the sandbox "runs clean" oracle (and the LLM) routinely miss them.

No LLM, no execution: each detector is a high-signal, low-false-positive AST pass.
Findings are emitted as bug-ledger ``LedgerIssue``s (severity ``warning``) so they
surface in the Issues tab and in the whole-file map the repair agent reads.

Current detectors:
  * mutable_default      — ``def f(x=[])`` / ``={}`` / ``=set()`` (shared across calls)
  * ignored_return       — a value-returning function/method called as a bare
                           statement (e.g. ``transfer`` ignoring ``withdraw()``'s
                           success/failure return)
  * shared_state_alias   — clone/copy methods assigning mutable ``self`` attrs to
                           the new object, or shallow-copying nested mutable attrs
  * swallowed_exception  — ``except ...: pass`` (errors silently hidden / masked)
"""
from __future__ import annotations

import ast

from backend.tools.bug_ledger import LedgerIssue


def semantic_lint(tree: ast.Module) -> list[LedgerIssue]:
    findings: list[LedgerIssue] = []
    findings += _mutable_defaults(tree)
    findings += _ignored_returns(tree)
    findings += _shared_state_aliases(tree)
    findings += _swallowed_exceptions(tree)
    findings += _infinite_loops(tree)
    findings += _background_threads(tree)
    return sorted(findings, key=lambda issue: issue.line or 0)


# ---------------------------------------------------------------------------
# mutable default arguments
# ---------------------------------------------------------------------------

def _is_mutable_default(node: ast.expr) -> bool:
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in {"list", "dict", "set", "bytearray", "defaultdict", "OrderedDict"}
    return False


def _mutable_defaults(tree: ast.Module) -> list[LedgerIssue]:
    out: list[LedgerIssue] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        positional = args.posonlyargs + args.args
        paired: list[tuple[ast.arg, ast.expr]] = []
        if args.defaults:
            paired += list(zip(positional[len(positional) - len(args.defaults):], args.defaults))
        paired += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
        for arg, default in paired:
            if _is_mutable_default(default):
                out.append(
                    LedgerIssue(
                        kind="mutable_default",
                        line=getattr(default, "lineno", node.lineno),
                        symbol=arg.arg,
                        message=(
                            f"mutable default argument '{arg.arg}=...' is shared across all calls; "
                            f"use None and create the value inside the function"
                        ),
                        severity="warning",
                    )
                )
    return out


# ---------------------------------------------------------------------------
# ignored return values
# ---------------------------------------------------------------------------

def _function_returns_value(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the function has a `return <non-None value>` (not descending into
    nested functions)."""
    stack: list[ast.AST] = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # a nested function's returns belong to it, not `fn`
        if isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                return True
        stack.extend(ast.iter_child_nodes(node))
    return False


def _ignored_returns(tree: ast.Module) -> list[LedgerIssue]:
    value_returning: set[str] = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _function_returns_value(node)
    }
    if not value_returning:
        return []

    out: list[LedgerIssue] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name and name in value_returning:
            out.append(
                LedgerIssue(
                    kind="ignored_return",
                    line=node.lineno,
                    symbol=name,
                    message=(
                        f"return value of '{name}()' is ignored — if it signals success/failure "
                        f"or carries the result, dropping it is likely a logic bug"
                    ),
                    severity="warning",
                )
            )
    return out


# ---------------------------------------------------------------------------
# shared mutable state in clone/copy methods
# ---------------------------------------------------------------------------

_COPY_METHOD_NAMES = {"clone", "copy", "__copy__"}
_MUTABLE_LITERAL_NODES = (ast.List, ast.Dict, ast.Set)
_MUTABLE_FACTORY_NAMES = {"list", "dict", "set", "bytearray", "defaultdict", "OrderedDict"}


def _is_mutable_initializer(node: ast.expr) -> bool:
    if isinstance(node, _MUTABLE_LITERAL_NODES):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in _MUTABLE_FACTORY_NAMES
    return False


def _self_attr(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return node.attr
    return None


def _assigned_self_attr(node: ast.Assign | ast.AnnAssign) -> str | None:
    target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0] if len(node.targets) == 1 else None
    return _self_attr(target) if target is not None else None


def _class_attr_evidence(cls: ast.ClassDef) -> tuple[set[str], set[str]]:
    """Return (mutable_attrs, nested_mutable_attrs) for ``self.<attr>`` fields.

    ``nested_mutable_attrs`` means the attribute is probably a list/container of
    mutable values, so a shallow copy still aliases inner state.
    """
    mutable: set[str] = set()
    nested: set[str] = set()

    for node in ast.walk(cls):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            attr = _assigned_self_attr(node)
            if attr and _is_mutable_initializer(node.value):
                mutable.add(attr)

        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
        ):
            continue

        attr = node.func.value.attr
        if node.func.attr in {"append", "insert"} and node.args and isinstance(node.args[-1], _MUTABLE_LITERAL_NODES):
            mutable.add(attr)
            nested.add(attr)
        elif node.func.attr == "extend" and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
            if any(isinstance(item, _MUTABLE_LITERAL_NODES) for item in node.args[0].elts):
                mutable.add(attr)
                nested.add(attr)

    return mutable, nested


def _new_instance_names(method: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(method):
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == class_name
        ):
            continue
        names.add(node.targets[0].id)
    return names


def _assigned_new_attr(node: ast.Assign | ast.AnnAssign, new_names: set[str]) -> str | None:
    target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0] if len(node.targets) == 1 else None
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id in new_names
    ):
        return target.attr
    return None


def _direct_self_attr_value(value: ast.expr) -> str | None:
    return _self_attr(value)


def _shallow_copied_self_attr(value: ast.expr) -> str | None:
    if not isinstance(value, ast.Call):
        return None

    # copy(self.items), list(self.items), dict(self.discounts), set(...)
    if isinstance(value.func, ast.Name) and value.func.id in {"copy", "list", "dict", "set"} and value.args:
        return _self_attr(value.args[0])

    # copy.copy(self.items)
    if (
        isinstance(value.func, ast.Attribute)
        and value.func.attr == "copy"
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "copy"
        and value.args
    ):
        return _self_attr(value.args[0])

    # self.items.copy()
    if isinstance(value.func, ast.Attribute) and value.func.attr == "copy":
        return _self_attr(value.func.value)

    return None


def _shared_state_aliases(tree: ast.Module) -> list[LedgerIssue]:
    out: list[LedgerIssue] = []
    for cls in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
        mutable_attrs, nested_mutable_attrs = _class_attr_evidence(cls)
        if not mutable_attrs:
            continue

        methods = [
            node
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and (node.name in _COPY_METHOD_NAMES or "clone" in node.name.lower())
        ]
        for method in methods:
            new_names = _new_instance_names(method, cls.name)
            if not new_names:
                continue
            for node in ast.walk(method):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                    continue
                target_attr = _assigned_new_attr(node, new_names)
                if not target_attr:
                    continue

                direct_attr = _direct_self_attr_value(node.value)
                if direct_attr and direct_attr in mutable_attrs:
                    out.append(
                        LedgerIssue(
                            kind="shared_state_alias",
                            line=node.lineno,
                            symbol=target_attr,
                            message=(
                                f"clone assigns mutable self.{direct_attr} directly to the new object; "
                                "the original and clone share state. Deep-copy or construct an independent value."
                            ),
                            severity="warning",
                        )
                    )
                    continue

                shallow_attr = _shallow_copied_self_attr(node.value)
                if shallow_attr and shallow_attr in nested_mutable_attrs:
                    out.append(
                        LedgerIssue(
                            kind="shared_state_alias",
                            line=node.lineno,
                            symbol=target_attr,
                            message=(
                                f"clone shallow-copies self.{shallow_attr}, whose elements are mutable; "
                                "nested changes in the clone can mutate the original. Use deepcopy."
                            ),
                            severity="warning",
                        )
                    )
    return out


# ---------------------------------------------------------------------------
# swallowed exceptions
# ---------------------------------------------------------------------------

def _swallowed_exceptions(tree: ast.Module) -> list[LedgerIssue]:
    out: list[LedgerIssue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            out.append(
                LedgerIssue(
                    kind="swallowed_exception",
                    line=node.lineno,
                    message="exception is silently swallowed (except: pass) — errors are hidden, not handled",
                    severity="warning",
                )
            )
    return out


# ---------------------------------------------------------------------------
# non-termination: infinite loops and module-level background threads
# ---------------------------------------------------------------------------

def _loop_has_exit(node: ast.While) -> bool:
    for n in ast.walk(node):
        if n is not node and isinstance(n, (ast.Break, ast.Return, ast.Raise)):
            return True
    return False


def _infinite_loops(tree: ast.Module) -> list[LedgerIssue]:
    out: list[LedgerIssue] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.While)
            and isinstance(node.test, ast.Constant)
            and node.test.value in (True, 1)
            and not _loop_has_exit(node)
        ):
            out.append(
                LedgerIssue(
                    kind="infinite_loop",
                    line=node.lineno,
                    message="infinite loop: `while True` with no reachable break/return/raise — runs forever if reached",
                    severity="warning",
                )
            )
    return out


_CONCURRENCY = {"threading", "multiprocessing"}


def _imports_concurrency(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] in _CONCURRENCY for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in _CONCURRENCY:
            return True
    return False


def _iter_module_level(stmts: list[ast.stmt]):
    """Yield statements that execute at *import time* — the module body plus the
    bodies of top-level control flow, but NOT anything inside a def/class."""
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield stmt
        for field in ("body", "orelse", "finalbody"):
            block = getattr(stmt, field, None)
            if isinstance(block, list):
                yield from _iter_module_level(block)
        if isinstance(stmt, ast.Try):
            for handler in stmt.handlers:
                yield from _iter_module_level(handler.body)


def _is_truthy_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and bool(node.value)


def _ctor_is_daemon(call: ast.Call) -> bool:
    """True if a Thread/Process constructor passes a truthy ``daemon=`` kwarg."""
    return any(kw.arg == "daemon" and _is_truthy_constant(kw.value) for kw in call.keywords)


def _daemon_thread_names(stmts) -> set[str]:
    """Names of module-level vars bound to a daemon thread/process.

    A daemon worker is killed when the main thread exits, so it does NOT keep the
    interpreter alive — it must not be treated as a non-termination blocker. We
    recognise ``daemon=True`` in the constructor, ``t.daemon = True``, and the
    legacy ``t.setDaemon(True)``."""
    names: set[str] = set()
    for stmt in _iter_module_level(stmts):
        # t = threading.Thread(target=f, daemon=True)
        if (
            isinstance(stmt, ast.Assign)
            and isinstance(stmt.value, ast.Call)
            and _ctor_is_daemon(stmt.value)
        ):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        # t.daemon = True
        elif (
            isinstance(stmt, ast.Assign)
            and _is_truthy_constant(stmt.value)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Attribute)
            and stmt.targets[0].attr == "daemon"
            and isinstance(stmt.targets[0].value, ast.Name)
        ):
            names.add(stmt.targets[0].value.id)
        # t.setDaemon(True)
        elif (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "setDaemon"
            and isinstance(stmt.value.func.value, ast.Name)
            and stmt.value.args
            and _is_truthy_constant(stmt.value.args[0])
        ):
            names.add(stmt.value.func.value.id)
    return names


def _background_threads(tree: ast.Module) -> list[LedgerIssue]:
    """A non-daemon thread/process started at module top level. Such workers keep
    the interpreter alive, so the file can never be run/validated headlessly — it
    hangs until the sandbox timeout. Daemon workers terminate with the main thread
    and are deliberately not flagged."""
    if not _imports_concurrency(tree):
        return []
    daemon_names = _daemon_thread_names(tree.body)
    out: list[LedgerIssue] = []
    for stmt in _iter_module_level(tree.body):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            if isinstance(func, ast.Attribute) and func.attr == "start":
                # Skip daemons: `t.start()` where t is a known daemon, or a chained
                # `Thread(..., daemon=True).start()`.
                if isinstance(func.value, ast.Name) and func.value.id in daemon_names:
                    continue
                if isinstance(func.value, ast.Call) and _ctor_is_daemon(func.value):
                    continue
                out.append(
                    LedgerIssue(
                        kind="background_thread",
                        line=stmt.lineno,
                        message=(
                            "thread/process started at module top level keeps the interpreter "
                            "alive and hangs headless execution — guard it under "
                            'if __name__ == "__main__" and use daemon=True / join()'
                        ),
                        severity="warning",
                    )
                )
    return out
