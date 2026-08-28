"""Safe evaluation of arithmetic expression strings.

The generator produces expressions; this module is the only thing that turns one
back into a number. It walks a parsed AST node by node and refuses anything that
is not integer arithmetic over the four basic operators — no name lookups, no
calls, no attribute access. Nothing here passes a string to `eval`, `exec` or a
dynamic compile.
"""

from __future__ import annotations

import ast

MULTIPLY_SIGN = "×"
DIVIDE_SIGN = "÷"


class ExpressionError(ValueError):
    """The expression is not valid integer arithmetic within our constraints."""


def to_plain(expression: str) -> str:
    """Turn a displayed expression back into standard Python operators."""
    return expression.replace(MULTIPLY_SIGN, "*").replace(DIVIDE_SIGN, "/")


def to_display(expression: str) -> str:
    """Turn a standard expression into the signs a schoolchild is taught."""
    return expression.replace("*", MULTIPLY_SIGN).replace("/", DIVIDE_SIGN)


def _node_value(node: ast.AST) -> int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            raise ExpressionError(f"Only integer constants are allowed, got {node.value!r}")
        return node.value

    if isinstance(node, ast.BinOp):
        left = _node_value(node.left)
        right = _node_value(node.right)

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            result = left - right
            if result < 0:
                raise ExpressionError(f"Negative intermediate result: {left} - {right}")
            return result
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ExpressionError("Division by zero")
            if left % right != 0:
                raise ExpressionError(f"Division is not exact: {left} / {right}")
            return left // right

        raise ExpressionError(f"Unsupported operator: {type(node.op).__name__}")

    raise ExpressionError(f"Unsupported syntax: {type(node).__name__}")


def evaluate(expression: str) -> int:
    """Evaluate a plain arithmetic expression, rejecting anything unexpected."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"Cannot parse expression {expression!r}") from exc
    return _node_value(tree.body)


def evaluate_display(expression: str) -> int:
    """Evaluate an expression written with `×` and `÷`."""
    return evaluate(to_plain(expression))
