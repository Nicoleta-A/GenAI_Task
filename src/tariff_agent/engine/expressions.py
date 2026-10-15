"""Safe expression evaluation for band/applies_when/times formulas."""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping
from typing import Any

from simpleeval import EvalWithCompoundTypes, SimpleEval

from tariff_agent.domain.exceptions import ExpressionSecurityError, UnknownFact

_ALLOWED_FUNCS: dict[str, Any] = {
    "ceil": math.ceil,
    "floor": math.floor,
    "min": min,
    "max": max,
    "abs": abs,
}

_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Call,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.IfExp,
)


def _assert_safe_ast(expr: str) -> ast.Expression:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionSecurityError(f"Invalid expression syntax: {expr}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            raise ExpressionSecurityError("Attribute access is not allowed")
        if isinstance(node, ast.Subscript):
            raise ExpressionSecurityError("Subscript access is not allowed")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ExpressionSecurityError("Imports are not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ExpressionSecurityError("Dunder names are not allowed")
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionSecurityError(f"Disallowed AST node: {type(node).__name__}")
    assert isinstance(tree, ast.Expression)
    return tree


def referenced_names(expr: str) -> set[str]:
    tree = _assert_safe_ast(expr)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_FUNCS and node.id not in {
            "True",
            "False",
            "None",
        }:
            names.add(node.id)
    return names


def safe_eval(expr: str, facts: Mapping[str, Any]) -> Any:
    """Evaluate a restricted expression against vessel facts."""
    _assert_safe_ast(expr)
    missing = referenced_names(expr) - set(facts.keys()) - set(_ALLOWED_FUNCS.keys())
    # True/False/None are literals in Python 3; referenced_names already skips them.
    if missing:
        raise UnknownFact(sorted(missing)[0])

    evaluator: SimpleEval = EvalWithCompoundTypes(
        names=dict(facts),
        functions=dict(_ALLOWED_FUNCS),
    )
    try:
        return evaluator.eval(expr)
    except Exception as exc:  # noqa: BLE001 - wrap library errors
        if isinstance(exc, (UnknownFact, ExpressionSecurityError)):
            raise
        raise ExpressionSecurityError(f"Evaluation failed for {expr!r}: {exc}") from exc
