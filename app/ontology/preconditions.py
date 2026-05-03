"""``@precondition("expr")`` — declarative state-machine guards on actions.

Each action in the ontology layer can be tagged with one or more
preconditions, expressed as a tiny safe-eval string against the loaded
object's metadata. The dispatch loop evaluates them right after the object
load; failure short-circuits the action with a clean error and writes a
``not_allowed`` audit row instead of mutating state.

Why a mini-language instead of Python lambdas?

  * It serialises — we expose the precondition strings via the catalog
    endpoint so the UI can grey-out illegal actions before the user clicks.
  * It cannot ``import os`` or call ``open()``: the evaluator whitelists
    comparison + membership operators only.

Supported expression shape::

    LHS OP RHS [AND/OR LHS OP RHS]*

  * ``LHS`` — dotted attribute path resolved against the object's
    ``metadata`` dict, e.g. ``stage`` or ``status.lifecycle``.
  * ``OP``  — one of ``==``, ``!=``, ``in``, ``not in``, ``<``, ``<=``,
    ``>``, ``>=``.
  * ``RHS`` — Python literal (``'prospect'``, ``42``, ``True``, list/tuple
    of literals).
  * Joiners — ``and`` / ``or``. Parens not supported (kept deliberately
    flat so the AST stays small and the failure message stays readable).

Examples bound on real actions::

    @precondition("stage in ['prospect','screened','grid_applied']")
    @precondition("status != 'archived'")
"""

from __future__ import annotations

import ast
import functools
import logging
from typing import Any, Callable, Iterable

from .base import ActionResult

log = logging.getLogger("princeps.ontology.preconditions")

# AST node types that are safe to evaluate. Anything else raises.
_ALLOWED_AST_NODES: tuple[type, ...] = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.Compare,
    ast.Name,
    ast.Constant,
    ast.Load,
    ast.Attribute,
    ast.List,
    ast.Tuple,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)

_PRECOND_ATTR = "__princeps_preconditions__"


class PreconditionError(ValueError):
    """Raised when a precondition expression is malformed at parse time.

    Runtime failures (e.g. attribute not on the object) are caught and
    surfaced as a *clean* False result — we don't want a typo in metadata
    to crash the whole dispatch loop.
    """


def _validate_ast(tree: ast.AST, expr: str) -> None:
    """Walk the AST and reject any node type we don't recognise."""
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise PreconditionError(
                f"precondition {expr!r} uses disallowed syntax: "
                f"{type(node).__name__}"
            )


def _resolve(obj: Any, name: str) -> Any:
    """Resolve a dotted name against the object's metadata + top-level attrs.

    Lookup order:
      1. ``obj.metadata[name]`` — most actions store their state here.
      2. ``getattr(obj, name)`` — direct attribute (e.g. ``id``).
      3. dotted path: walk metadata + attrs together.

    Returns ``None`` if any segment is missing — a None LHS in a comparison
    almost always evaluates to False, which is the safe answer.
    """
    parts = name.split(".")
    cur: Any
    metadata = getattr(obj, "metadata", None)

    head, *rest = parts
    if metadata is not None and isinstance(metadata, dict) and head in metadata:
        cur = metadata[head]
    elif hasattr(obj, head):
        cur = getattr(obj, head)
    else:
        return None

    for seg in rest:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(seg)
            continue
        cur = getattr(cur, seg, None)
    return cur


def _eval(node: ast.AST, obj: Any) -> Any:
    """Recursively evaluate a whitelisted AST node against ``obj``."""
    if isinstance(node, ast.Expression):
        return _eval(node.body, obj)

    if isinstance(node, ast.BoolOp):
        # short-circuit semantics matter for clean error messages
        if isinstance(node.op, ast.And):
            for v in node.values:
                if not _eval(v, obj):
                    return False
            return True
        if isinstance(node.op, ast.Or):
            for v in node.values:
                if _eval(v, obj):
                    return True
            return False

    if isinstance(node, ast.Compare):
        left = _eval(node.left, obj)
        for op, right_node in zip(node.ops, node.comparators):
            right = _eval(right_node, obj)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Lt):
                ok = left is not None and right is not None and left < right
            elif isinstance(op, ast.LtE):
                ok = left is not None and right is not None and left <= right
            elif isinstance(op, ast.Gt):
                ok = left is not None and right is not None and left > right
            elif isinstance(op, ast.GtE):
                ok = left is not None and right is not None and left >= right
            elif isinstance(op, ast.In):
                ok = left in (right or [])
            elif isinstance(op, ast.NotIn):
                ok = left not in (right or [])
            else:  # pragma: no cover — _validate_ast already filtered
                raise PreconditionError(f"unsupported comparison: {type(op).__name__}")
            if not ok:
                return False
            left = right
        return True

    if isinstance(node, ast.Name):
        return _resolve(obj, node.id)

    if isinstance(node, ast.Attribute):
        # Reconstruct dotted name and re-resolve as a single path.
        path: list[str] = [node.attr]
        cur: ast.AST = node.value
        while isinstance(cur, ast.Attribute):
            path.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            path.append(cur.id)
        else:
            raise PreconditionError("attribute LHS must be a name chain")
        return _resolve(obj, ".".join(reversed(path)))

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e, obj) for e in node.elts]

    raise PreconditionError(f"unsupported node: {type(node).__name__}")


def evaluate(expr: str, obj: Any) -> bool:
    """Parse + evaluate a precondition string against ``obj``. Returns bool."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise PreconditionError(f"precondition {expr!r} parse error: {e}") from e
    _validate_ast(tree, expr)
    try:
        return bool(_eval(tree, obj))
    except PreconditionError:
        raise
    except Exception as e:
        # Runtime resolution error — log and return False (deny by default).
        log.warning("precondition %r runtime error: %s", expr, e)
        return False


def precondition(expr: str) -> Callable:
    """Decorator: tag an action handler with a state-machine guard.

    Stacks on a list, so multiple ``@precondition`` decorators are AND-ed
    in declaration order (top-most decorator runs first when checked).
    """
    # Eager parse so a typo in the expression fails at import, not at call.
    try:
        tree = ast.parse(expr, mode="eval")
        _validate_ast(tree, expr)
    except PreconditionError:
        raise
    except SyntaxError as e:
        raise PreconditionError(f"precondition {expr!r} parse error: {e}") from e

    def _decorate(fn: Callable) -> Callable:
        existing = getattr(fn, _PRECOND_ATTR, [])
        # New decorator goes first so that the syntactically-outer guard
        # (closest to the def) is checked last — matches Python's intuition
        # that ``@a / @b / def f`` reads top-down as a > b > f.
        setattr(fn, _PRECOND_ATTR, [expr] + list(existing))

        @functools.wraps(fn)
        async def _wrapped(*args, **kwargs):
            return await fn(*args, **kwargs)

        # Preserve the metadata on the wrapper too so dispatch.py can read
        # it after ``functools.wraps`` strips most things.
        setattr(_wrapped, _PRECOND_ATTR, getattr(fn, _PRECOND_ATTR))
        return _wrapped

    return _decorate


def get_preconditions(handler: Callable) -> list[str]:
    """Return the list of precondition expressions bound to ``handler``."""
    return list(getattr(handler, _PRECOND_ATTR, []))


def check_preconditions(
    handler: Callable, obj: Any
) -> tuple[bool, str | None]:
    """Run every precondition on ``handler``. Return (ok, failed_expr)."""
    for expr in get_preconditions(handler):
        if not evaluate(expr, obj):
            return False, expr
    return True, None


def precondition_failed(object_key: str, expr: str) -> ActionResult:
    """Build the ``ActionResult`` returned when a precondition rejects."""
    return ActionResult(
        ok=False,
        object_key=object_key,
        error=f"precondition_failed: {expr}",
        reason=f"precondition_failed: {expr}",
        provenance={"check": "ontology.preconditions", "expr": expr},
    )


__all__ = [
    "PreconditionError",
    "check_preconditions",
    "evaluate",
    "get_preconditions",
    "precondition",
    "precondition_failed",
]
