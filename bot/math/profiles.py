"""Grade profiles: what a problem may look like for a given school year.

A profile is chosen by the user and never changes on its own. It fixes the
number range, which operations may appear and how often, and the band of
difficulties the adaptive scale may move through.

Difficulty is ascending everywhere: a larger number means a harder problem. It
maps directly to the number of operators in the generated expression.
"""

from __future__ import annotations

from dataclasses import dataclass

ADD = "+"
SUB = "-"
MUL = "*"
DIV = "/"

#: Hard limit shared by every profile: in any multiplication at least one
#: operand must be small enough to multiply in your head.
MAX_SMALL_FACTOR = 10


@dataclass(frozen=True)
class GradeProfile:
    """The rules a generated problem must obey for one school year."""

    key: str
    title: str
    description: str

    #: Largest value any operand or intermediate result may take.
    max_value: int
    #: Range the final answer is drawn from.
    min_answer: int
    max_answer: int
    #: Largest divisor a division may use.
    max_divisor: int

    #: Relative weights for choosing an operation while building an expression.
    op_weights: dict[str, float]

    #: Difficulty (operator count) bounds for the adaptive scale.
    min_difficulty: int
    max_difficulty: int

    #: Acceptable share of generated problems containing at least one division,
    #: asserted by the test suite so a regression cannot silently kill division
    #: again the way the pre-rewrite generator did.
    division_share_band: tuple[float, float]

    def ops(self) -> tuple[str, ...]:
        return tuple(op for op, weight in self.op_weights.items() if weight > 0)

    def clamp_difficulty(self, difficulty: int) -> int:
        return max(self.min_difficulty, min(self.max_difficulty, difficulty))


GRADE3 = GradeProfile(
    key="grade3",
    title="3 класс",
    description="Числа до 100, все четыре действия",
    max_value=100,
    min_answer=5,
    max_answer=100,
    max_divisor=10,
    op_weights={ADD: 0.3, SUB: 0.3, MUL: 0.2, DIV: 0.2},
    min_difficulty=1,
    max_difficulty=4,
    division_share_band=(0.08, 0.60),
)

GRADE4 = GradeProfile(
    key="grade4",
    title="4 класс",
    description="Числа до 1000 и больше, многозначное умножение и деление",
    max_value=3_000,
    min_answer=20,
    max_answer=1_200,
    max_divisor=12,
    op_weights={ADD: 0.28, SUB: 0.27, MUL: 0.22, DIV: 0.23},
    min_difficulty=1,
    max_difficulty=5,
    division_share_band=(0.20, 0.85),
)

PROFILES: dict[str, GradeProfile] = {p.key: p for p in (GRADE3, GRADE4)}

DEFAULT_PROFILE = GRADE3.key


def get_profile(key: str | None) -> GradeProfile:
    """Look up a profile, falling back to the default for unknown keys."""
    if key and key in PROFILES:
        return PROFILES[key]
    return PROFILES[DEFAULT_PROFILE]
