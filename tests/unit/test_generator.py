"""Constraint sweeps over the generator.

These run over thousands of generated problems rather than a handful of
examples, because the defects this generator replaced were statistical: division
that never appeared, and an intermediate value that only strayed out of range on
particular tree shapes.
"""

from __future__ import annotations

import ast
import random

import pytest

from bot.math import generate
from bot.math.evaluator import ExpressionError, evaluate, evaluate_display, to_plain
from bot.math.profiles import MAX_SMALL_FACTOR, PROFILES

SAMPLE = 400


def _walk(expression: str):
    """Yield every (op, left value, right value, result) in evaluation order."""
    tree = ast.parse(to_plain(expression), mode="eval")

    def visit(node: ast.AST) -> int:
        if isinstance(node, ast.Constant):
            return int(node.value)
        assert isinstance(node, ast.BinOp)
        left = visit(node.left)
        right = visit(node.right)
        op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}[type(node.op)]
        result = {
            "+": left + right,
            "-": left - right,
            "*": left * right,
            "/": left // right if right and left % right == 0 else None,
        }[op]
        steps.append((op, left, right, result))
        assert result is not None
        return result

    steps: list[tuple[str, int, int, int | None]] = []
    visit(tree.body)
    return steps


@pytest.mark.parametrize("profile_key", sorted(PROFILES))
def test_every_problem_satisfies_its_profile(profile_key: str) -> None:
    profile = PROFILES[profile_key]
    rng = random.Random(20260829)

    for difficulty in range(profile.min_difficulty, profile.max_difficulty + 1):
        for _ in range(SAMPLE):
            problem = generate(difficulty, profile_key, rng)

            assert evaluate_display(problem.expression) == problem.answer, problem
            assert problem.operator_count == difficulty, problem
            assert 1 <= problem.answer <= profile.max_value, problem

            for op, left, right, result in _walk(problem.expression):
                assert left >= 0 and right >= 0, (op, left, right, problem)
                assert result is not None and result >= 0, (op, left, right, problem)
                assert result <= profile.max_value, (op, left, right, problem)
                assert left <= profile.max_value and right <= profile.max_value, problem
                if op == "*":
                    assert min(left, right) <= MAX_SMALL_FACTOR, problem
                if op == "/":
                    assert right != 0 and left % right == 0, problem
                    assert right <= profile.max_divisor, problem


@pytest.mark.parametrize("profile_key", sorted(PROFILES))
def test_division_share_is_inside_the_profile_band(profile_key: str) -> None:
    """Division must keep appearing.

    The pre-rewrite generator type-checked the result of `eval("a / b")` against
    `int`, which a division never returns, so division vanished from every
    composite expression. A share, not a mere presence check, is what stops that
    regressing.
    """
    profile = PROFILES[profile_key]
    low, high = profile.division_share_band
    rng = random.Random(4242)

    for difficulty in range(profile.min_difficulty, profile.max_difficulty + 1):
        with_division = sum(
            "÷" in generate(difficulty, profile_key, rng).expression for _ in range(SAMPLE)
        )
        share = with_division / SAMPLE
        assert low <= share <= high, (
            f"{profile_key} difficulty {difficulty}: division share {share:.3f} "
            f"outside band {low}..{high}"
        )


@pytest.mark.parametrize("profile_key", sorted(PROFILES))
def test_harder_difficulty_means_more_operators(profile_key: str) -> None:
    profile = PROFILES[profile_key]
    rng = random.Random(7)
    easiest = [
        generate(profile.min_difficulty, profile_key, rng).operator_count for _ in range(200)
    ]
    hardest = [
        generate(profile.max_difficulty, profile_key, rng).operator_count for _ in range(200)
    ]
    assert sum(hardest) / len(hardest) > sum(easiest) / len(easiest)


def test_difficulty_is_clamped_into_the_profile() -> None:
    profile = PROFILES["grade3"]
    assert generate(99, "grade3").operator_count <= profile.max_difficulty
    assert generate(-5, "grade3").operator_count >= profile.min_difficulty


def test_grade4_reaches_beyond_a_thousand() -> None:
    rng = random.Random(11)
    answers = [generate(3, "grade4", rng).answer for _ in range(SAMPLE)]
    assert max(answers) > 1000


def test_unknown_profile_falls_back_to_the_default() -> None:
    assert generate(1, "grade99").profile == "grade3"


def test_displayed_expression_uses_school_signs() -> None:
    rng = random.Random(3)
    for _ in range(200):
        expression = generate(3, "grade4", rng).expression
        assert "*" not in expression and "/" not in expression


class TestEvaluator:
    def test_rejects_names_and_calls(self) -> None:
        for source in ("__import__('os')", "x + 1", "len([1])", "1 if True else 2"):
            with pytest.raises(ExpressionError):
                evaluate(source)

    def test_rejects_broken_arithmetic(self) -> None:
        for source in ("5 - 9", "7 / 2", "1 / 0", "2 ** 3", "1.5 + 1"):
            with pytest.raises(ExpressionError):
                evaluate(source)

    def test_computes_with_precedence(self) -> None:
        assert evaluate("2 + 3 * 4") == 14
        assert evaluate("(2 + 3) * 4") == 20
        assert evaluate("100 / 4 / 5") == 5
