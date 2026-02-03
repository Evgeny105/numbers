"""
Генератор математических выражений для тренировки устного счёта.

Создаёт примеры с ограничениями: все промежуточные результаты положительные,
целые числа, при умножении хотя бы один множитель не больше 10.
"""

import ast
import logging
import random
from enum import Enum
from typing import NamedTuple

_LOGGER = logging.getLogger(__name__)

# ============================================================================
# Константы
# ============================================================================

# Максимальная глубина рекурсии при генерации сложных выражений
MAX_DIFICULTY = 5

# ============================================================================
# Перечисления и типы
# ============================================================================


class OpPriority(Enum):
    """Приоритет арифметических операций для определения необходимости скобок."""
    ADD_SUB = 1  # Сложение и вычитание
    MUL_DIV = 2  # Умножение и деление


class Expression(NamedTuple):
    """
    Контейнер для математического выражения.

    Attributes:
        expr: Строковое представление выражения (может содержать скобки)
        value: Вычисленное значение выражения
        priority: Приоритет верхней операции в выражении (для правильной расстановки скобок)
    """

    expr: str
    value: int
    priority: OpPriority | None = None


# ============================================================================
# Генерация простых выражений
# ============================================================================


def generate_simple_expression() -> Expression:
    """
    Генерирует простое выражение: одиночное число или бинарную операцию a op b.

    Returns:
        Expression: Выражение со строкой, значением и приоритетом операции.

    Note:
        - Для умножения: первый множитель 10-99, второй 2-9 (ограничение для устного счёта)
        - Для деления: результат всегда целый, делитель 2-10
        - Отрицательные и дробные результаты отклоняются (рекурсивная попытка заново)
    """
    if random.random() < 0.5:
        # Случай 1: просто число
        num: int = random.randint(1, 50)
        return Expression(str(num), num)
    else:
        # Случай 2: бинарная операция a op b
        a: int = random.randint(1, 50)
        b: int = random.randint(1, 50)
        op: str = random.choice(["+", "-", "*", "/"])

        # Проверка ограничений для операции
        if op == "*":
            # Для умножения один множитель должен быть ≤ 10
            a = random.randint(10, 99)
            b = random.randint(2, 9)
        elif op == "/":
            # Для деления результат должен быть целым
            b = random.randint(2, 10)
            a = b * random.randint(1, 50 // b)

        expr_str: str = f"{a} {op} {b}"
        try:
            value: float = eval(expr_str)
            if value < 0 or value != int(value):
                return generate_simple_expression()
            value = int(value)
        except (ZeroDivisionError, ValueError, TypeError):
            return generate_simple_expression()

        priority: OpPriority = (
            OpPriority.MUL_DIV if op in ["*", "/"] else OpPriority.ADD_SUB
        )
        return Expression(
            f"({expr_str})" if priority == OpPriority.ADD_SUB else expr_str,
            value,
            priority,
        )


# ============================================================================
# Работа со скобками и приоритетами
# ============================================================================


def maybe_parenthesize(
    expr: Expression,
    current_priority: OpPriority | None,
    parent_priority: OpPriority | None,
) -> str:
    """
    Добавляет скобки вокруг выражения при необходимости сохранения приоритета операций.

    Скобки нужны, когда приоритет операции внутри подвыражения ниже приоритета
    родительской операции. Например: в "(a + b) * c" нужны скобки, потому что
    сложение (приоритет 1) должно выполниться раньше умножения (приоритет 2).

    Args:
        expr: Выражение для анализа
        current_priority: Приоритет операции внутри expr (не используется, оставлен для совместимости)
        parent_priority: Приоритет операции, в которую вставляется expr

    Returns:
        expr.expr в скобках или без, в зависимости от приоритетов
    """
    if (
        not (expr.expr.startswith("(") and expr.expr.endswith(")"))
        and parent_priority
        and expr.priority
        and expr.priority.value < parent_priority.value
    ):
        return f"({expr.expr})"
    return expr.expr


# ============================================================================
# Комбинирование выражений
# ============================================================================


def combine_expressions(
    expr1: Expression, expr2: Expression, op: str
) -> Expression | None:
    """
    Объединяет два выражения бинарной операцией, корректно расставляя скобки.

    Args:
        expr1: Левое подвыражение
        expr2: Правое подвыражение
        op: Операция ('+', '-', '*', '/')

    Returns:
        Expression: Объединённое выражение или None, если результат некорректен
                   (отрицательный, нецелый или неудачные промежуточные значения)
    """
    new_priority: OpPriority = (
        OpPriority.MUL_DIV if op in ["*", "/"] else OpPriority.ADD_SUB
    )

    # Форматируем подвыражения со скобками при необходимости
    left: str = maybe_parenthesize(expr1, expr1.priority, new_priority)
    right: str = maybe_parenthesize(expr2, expr2.priority, new_priority)

    new_expr: str = f"{left} {op} {right}"
    try:
        # Проверяем промежуточные результаты через AST
        if not check_intermediate_results(new_expr):
            return None
        value: float = eval(new_expr)
        if value < 0 or not isinstance(value, int):
            return None
        return Expression(new_expr, int(value), new_priority)
    except (ZeroDivisionError, ValueError, TypeError):
        return None


# ============================================================================
# Рекурсивная генерация сложных выражений
# ============================================================================


def generate_expression(depth: int = 0) -> Expression:
    """
    Рекурсивно генерирует сложное выражение заданной глубины.

    Алгоритм:
        1. Если достигнута максимальная глубина — возвращает простое выражение
        2. Иначе рекурсивно генерирует два подвыражения
        3. Пытается соединить их случайной операцией (+, -, *, /)
        4. Если ни одна операция не подходит — возвращает простое выражение

    Args:
        depth: Текущая глубина рекурсии

    Returns:
        Expression: Сгенерированное выражение
    """
    if depth >= MAX_DIFICULTY:
        return generate_simple_expression()

    expr1: Expression = generate_expression(depth + 1)
    expr2: Expression = generate_expression(depth + 1)

    for op in random.sample(["+", "-", "*", "/"], k=4):
        new_expr: Expression | None = combine_expressions(expr1, expr2, op)
        if new_expr:
            return new_expr
    return generate_simple_expression()


# ============================================================================
# Проверка промежуточных результатов
# ============================================================================


def check_intermediate_results(expression: str) -> bool:
    """
    Проверяет, что все промежуточные результаты вычисления корректны.

    Вычисляет выражение через AST (безопасный разбор синтаксического дерева),
    проверяя каждый шаг вычислений на соответствие ограничениям устного счёта.

    Ограничения:
        - Никаких отрицательных чисел (даже промежуточных)
        - Умножение: хотя бы один множитель ≤ 10
        - Деление: только целочисленное, без остатка

    Args:
        expression: Строка с математическим выражением

    Returns:
        True, если все промежуточные результаты корректны, иначе False
    """
    try:
        tree: ast.Expression = ast.parse(expression, mode="eval")

        def evaluate_node(node: ast.AST) -> int:
            """Рекурсивно вычисляет значение узла AST с проверкой ограничений."""
            if isinstance(node, ast.Constant):  # Python 3.8+
                return int(node.value)
            elif isinstance(
                node, ast.Num
            ):  # Python 3.7 и ниже для совместимости
                return node.n
            elif isinstance(node, ast.BinOp):
                left: int = evaluate_node(node.left)
                right: int = evaluate_node(node.right)

                if isinstance(node.op, ast.Add):
                    res: int = left + right
                elif isinstance(node.op, ast.Sub):
                    res = left - right
                    if res < 0:
                        raise ValueError("Negative intermediate")
                elif isinstance(node.op, ast.Mult):
                    res = left * right
                    if min(left, right) > 10:
                        raise ValueError("Intermediate too large")
                elif isinstance(node.op, ast.Div):
                    if right == 0:
                        raise ZeroDivisionError("Division by zero")
                    if left % right != 0:
                        raise ValueError("Non-integer division")
                    res = left // right
                else:
                    raise NotImplementedError(
                        f"Unsupported operation: {type(node.op)}"
                    )
                return res
            raise NotImplementedError(f"Unsupported node type: {type(node)}")

        evaluate_node(tree.body)
        return True
    except (ValueError, ZeroDivisionError, NotImplementedError, TypeError):
        _LOGGER.debug(f"Expression rejected: {expression}")
        return False
    except Exception as e:
        _LOGGER.error(
            f"Unexpected error checking expression '{expression}': {e}"
        )
        return False


# ============================================================================
# Главная функция генерации
# ============================================================================


def generate(difficulty: int) -> tuple[str, int]:
    """
    Генерирует пример заданной сложности для устного счёта.

    Сложность инвертирована: difficulty=0 даёт максимальную сложность,
    difficulty=MAX_DIFICULTY — простое выражение.

    Алгоритм поиска:
        - Генерирует выражения до тех пор, пока не найдётся сложное
          (т.е. содержащее хотя бы одну операцию, не являющееся просто числом)

    Args:
        difficulty: Уровень сложности (0..MAX_DIFICULTY)

    Returns:
        tuple: (выражение_с_заменёнными_символами, ответ)
               Пример: ("12 × 3 + 5 = ?", 41)
    """
    # Инвертируем сложность: difficulty=0 → максимальная глубина
    depth: int = MAX_DIFICULTY - difficulty

    _LOGGER.info(f"Генерация примера сложности {difficulty} (глубина {depth})")

    # Генерируем выражения, пока не найдём достаточно сложное
    # (содержащее операции, а не просто число)
    while True:
        expr: Expression = generate_expression(depth=depth)
        try:
            # Если выражение — просто число, продолжаем поиск
            if int(expr.expr) == expr.value:
                continue
        except (ValueError, TypeError):
            # Выражение содержит операции — это то, что нужно
            break

    # Заменяем символы на более "учебные" варианты для отображения
    str_expr: str = expr.expr.replace("*", "×").replace("/", "÷")

    _LOGGER.info(f"Пример: {str_expr}")
    _LOGGER.info(f"Ответ: {expr.value}")

    return str_expr, expr.value
