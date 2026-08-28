"""Building arithmetic problems that satisfy every constraint by construction.

The previous generator worked by rejection sampling: pick an operation at
random, build a candidate, throw it away if a constraint failed. Division fails
that lottery far more often than the other operations, and a type check against
a float made composite division fail *always*, so division effectively vanished
from the bot's problems.

This generator inverts the process. It picks the answer first, then decomposes
that answer into an expression tree, choosing each operation by weight and then
*constructing* operands that satisfy it. Nothing is generated and discarded, so
the operation mix in the output matches the profile's weights.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import NamedTuple

from bot.math.evaluator import evaluate, to_display
from bot.math.profiles import (
    ADD,
    DIV,
    MAX_SMALL_FACTOR,
    MUL,
    SUB,
    GradeProfile,
    get_profile,
)

_LOGGER = logging.getLogger(__name__)

#: How many times to rebuild before accepting an expression with fewer operators
#: than requested. Failure to hit the target is rare and harmless — the child
#: gets a slightly easier problem, not a broken one.
_BUILD_ATTEMPTS = 12

_PRECEDENCE = {ADD: 1, SUB: 1, MUL: 2, DIV: 2}


class Problem(NamedTuple):
    """A generated problem ready to be shown to a user."""

    expression: str
    """The expression as displayed, using `×` and `÷`."""

    answer: int
    """Its value."""

    operator_count: int
    """How many operators it actually contains."""

    profile: str
    """The grade profile it was generated for."""

    difficulty: int
    """The difficulty it was generated at."""


@dataclass(frozen=True)
class _Node:
    """A node of the expression tree: a leaf if `op` is None."""

    value: int
    op: str | None = None
    left: "_Node | None" = None
    right: "_Node | None" = None

    @property
    def is_leaf(self) -> bool:
        return self.op is None

    def operator_count(self) -> int:
        if self.is_leaf:
            return 0
        assert self.left is not None and self.right is not None
        return 1 + self.left.operator_count() + self.right.operator_count()


class _BuildFailed(Exception):
    """This branch cannot be built; the caller should try another operation."""


def _weighted_order(profile: GradeProfile, rng: random.Random) -> list[str]:
    """Shuffle the operations into a weighted-random order of preference.

    Every operation stays in the list, so a decomposition that turns out to be
    impossible for the preferred one falls through to the next rather than
    forcing a rebuild — but the *first* choice follows the profile's weights,
    which is what determines the operation mix of the output.
    """
    remaining = {op: w for op, w in profile.op_weights.items() if w > 0}
    order: list[str] = []
    while remaining:
        total = sum(remaining.values())
        pick = rng.uniform(0, total)
        running = 0.0
        chosen = next(iter(remaining))
        for op, weight in remaining.items():
            running += weight
            if pick <= running:
                chosen = op
                break
        order.append(chosen)
        del remaining[chosen]
    return order


def _divisors_up_to(value: int, limit: int) -> list[int]:
    """Divisors of `value` in [2, limit] whose cofactor is also at least 2."""
    return [d for d in range(2, limit + 1) if value % d == 0 and value // d >= 2]


def _decompose(
    value: int, op: str, profile: GradeProfile, rng: random.Random
) -> tuple[int, int]:
    """Split `value` into two operands joined by `op`, or fail.

    Every constraint the bot cares about is enforced here, at construction time:
    non-negative intermediates, exact division, and a small factor in every
    multiplication.
    """
    if op == ADD:
        if value < 2:
            raise _BuildFailed("addition needs a value of at least 2")
        # Keep both halves meaningful; `97 + 1` is not worth a child's time.
        low, high = (2, value - 2) if value >= 10 else (1, value - 1)
        left = rng.randint(low, high)
        return left, value - left

    if op == SUB:
        headroom = profile.max_value - value
        if headroom < 1:
            raise _BuildFailed("subtraction would exceed the profile's range")
        # Bound the subtrahend by the answer range rather than by the headroom,
        # so the operands stay the size of the answers rather than drifting up
        # towards the intermediate-value ceiling.
        subtrahend = rng.randint(1, min(headroom, profile.max_answer))
        return value + subtrahend, subtrahend

    if op == MUL:
        factors = _divisors_up_to(value, MAX_SMALL_FACTOR)
        if not factors:
            raise _BuildFailed(f"{value} has no small factor to multiply back from")
        small = rng.choice(factors)
        large = value // small
        if large > profile.max_value:
            raise _BuildFailed("multiplication operand exceeds the profile's range")
        # Either order is fine: one operand is always at most MAX_SMALL_FACTOR.
        return (small, large) if rng.random() < 0.5 else (large, small)

    if op == DIV:
        candidates = [
            m for m in range(2, profile.max_divisor + 1) if value * m <= profile.max_value
        ]
        if not candidates:
            raise _BuildFailed("division would exceed the profile's range")
        divisor = rng.choice(candidates)
        return value * divisor, divisor

    raise _BuildFailed(f"unknown operation {op!r}")


def _build(value: int, operators: int, profile: GradeProfile, rng: random.Random) -> _Node:
    """Build a tree with `operators` operators that evaluates to `value`."""
    if operators <= 0:
        if not 1 <= value <= profile.max_value:
            raise _BuildFailed(f"leaf {value} is outside the profile's range")
        return _Node(value=value)

    for op in _weighted_order(profile, rng):
        try:
            left_value, right_value = _decompose(value, op, profile, rng)
        except _BuildFailed:
            continue

        remaining = operators - 1
        left_ops = rng.randint(0, remaining)
        right_ops = remaining - left_ops

        try:
            left = _build(left_value, left_ops, profile, rng)
            right = _build(right_value, right_ops, profile, rng)
        except _BuildFailed:
            # Try the same operands with everything below them flattened before
            # giving up on this operation entirely.
            try:
                left = _build(left_value, 0, profile, rng)
                right = _build(right_value, 0, profile, rng)
            except _BuildFailed:
                continue

        return _Node(value=value, op=op, left=left, right=right)

    raise _BuildFailed(f"cannot decompose {value} with {operators} operators")


def _render(node: _Node, parent_op: str | None = None, is_right_child: bool = False) -> str:
    """Render the tree, adding parentheses only where precedence requires them."""
    if node.is_leaf:
        return str(node.value)

    assert node.op is not None and node.left is not None and node.right is not None
    text = (
        f"{_render(node.left, node.op, False)} "
        f"{node.op} "
        f"{_render(node.right, node.op, True)}"
    )

    if parent_op is None:
        return text

    own = _PRECEDENCE[node.op]
    parent = _PRECEDENCE[parent_op]
    # Lower precedence inside higher always needs brackets. Equal precedence
    # needs them on the right, always — not only where the parent operation is
    # non-associative. `2 * (64 / 4)` and `2 * 64 / 4` agree on the answer but
    # not on the intermediate a child computes reading left to right, and the
    # intermediate is exactly what the profile's range is supposed to bound.
    if own < parent or (own == parent and is_right_child):
        return f"({text})"
    return text


def generate(
    difficulty: int,
    profile_key: str | None = None,
    rng: random.Random | None = None,
) -> Problem:
    """Generate one problem at the given ascending difficulty.

    Difficulty maps to the number of operators: larger means harder. It is
    clamped into the profile's own bounds, so a profile can never be pushed
    outside the material it is meant to cover.
    """
    rng = rng or random
    profile = get_profile(profile_key)
    operators = profile.clamp_difficulty(difficulty)

    best: _Node | None = None
    for _ in range(_BUILD_ATTEMPTS):
        answer = rng.randint(profile.min_answer, profile.max_answer)
        try:
            node = _build(answer, operators, profile, rng)
        except _BuildFailed:
            continue
        if node.operator_count() == operators:
            best = node
            break
        if best is None or node.operator_count() > best.operator_count():
            best = node

    if best is None or best.is_leaf:
        # Nothing worked at this difficulty — fall back to a single operation,
        # which is always constructible.
        answer = rng.randint(profile.min_answer, profile.max_answer)
        best = _build(answer, 1, profile, rng)

    plain = _render(best)
    value = evaluate(plain)
    if value != best.value:  # pragma: no cover - guards a rendering bug
        raise AssertionError(
            f"rendered expression {plain!r} evaluates to {value}, expected {best.value}"
        )

    problem = Problem(
        expression=to_display(plain),
        answer=best.value,
        operator_count=best.operator_count(),
        profile=profile.key,
        difficulty=operators,
    )
    _LOGGER.debug(
        "generated %s = %s (profile=%s difficulty=%s)",
        problem.expression,
        problem.answer,
        problem.profile,
        problem.difficulty,
    )
    return problem
