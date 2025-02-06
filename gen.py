import ast
import logging
import random
from enum import Enum

_LOGGER = logging.getLogger(__name__)

MAX_DIFICULTY = 5


class OpPriority(Enum):
    ADD_SUB = 1
    MUL_DIV = 2


class Expression:
    def __init__(self, expr: str, value: int, priority=None):
        self.expr = expr
        self.value = value
        self.priority = priority  # Приоритет "верхней" операции


def generate_simple_expression():
    # Генерация простого выражения: число или a op b
    if random.random() < 0.5:
        num = random.randint(1, 50)
        return Expression(str(num), num)
    else:
        a = random.randint(1, 50)
        b = random.randint(1, 50)
        op = random.choice(["+", "-", "*", "/"])

        # Проверка ограничений для операции
        if op == "*":
            a = random.randint(10, 99)
            b = random.randint(2, 9)
        elif op == "/":
            b = random.randint(2, 10)
            a = b * random.randint(1, 50 // b)

        expr_str = f"{a} {op} {b}"  # if op != '/' else f"{a}{op}{b}"
        try:
            value = eval(expr_str)
            if value < 0 or value != int(value):
                return generate_simple_expression()
            value = int(value)
        except:
            return generate_simple_expression()

        priority = (
            OpPriority.MUL_DIV if op in ["*", "/"] else OpPriority.ADD_SUB
        )
        return Expression(
            f"({expr_str})" if priority == OpPriority.ADD_SUB else expr_str,
            value,
            priority,
        )


def maybe_parenthesize(expr, current_priority, parent_priority):
    # Добавляем скобки, если приоритет подвыражения ниже текущего
    if (
        not (expr.expr.startswith("(") and expr.expr.endswith(")"))
        and parent_priority
        and expr.priority
        and parent_priority
        and expr.priority.value < parent_priority.value
    ):
        return f"({expr.expr})"
    return expr.expr


def combine_expressions(expr1, expr2, op):
    # Определяем приоритет новой операции
    new_priority = (
        OpPriority.MUL_DIV if op in ["*", "/"] else OpPriority.ADD_SUB
    )

    # Форматируем подвыражения со скобками при необходимости
    left = maybe_parenthesize(expr1, expr1.priority, new_priority)
    right = maybe_parenthesize(expr2, expr2.priority, new_priority)

    new_expr = f"{left} {op} {right}"
    try:
        # Проверяем промежуточные результаты через AST
        if not check_intermediate_results(new_expr):
            return None
        value = eval(new_expr)
        if value < 0 or not isinstance(value, int):
            return None
        return Expression(new_expr, value, new_priority)
    except:
        return None


def generate_expression(depth=0):
    if depth >= MAX_DIFICULTY:
        return generate_simple_expression()

    expr1 = generate_expression(depth + 1)
    expr2 = generate_expression(depth + 1)

    for op in random.sample(["+", "-", "*", "/"], k=4):
        new_expr = combine_expressions(expr1, expr2, op)
        if new_expr:
            return new_expr
    return generate_simple_expression()


def check_intermediate_results(expression):
    try:
        tree = ast.parse(expression, mode="eval")

        def evaluate_node(node):
            if isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                left = evaluate_node(node.left)
                right = evaluate_node(node.right)

                if isinstance(node.op, ast.Add):
                    res = left + right
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
                        raise ZeroDivisionError
                    if left % right != 0:
                        raise ValueError("Non-integer division")
                    res = left // right
                else:
                    raise NotImplementedError
                return res
            raise NotImplementedError

        evaluate_node(tree.body)
        return True
    except:
        return False


def generate(difficulty):
    # for difficulty in range(0, MAX_DIFICULTY):
    j = MAX_DIFICULTY - difficulty
    print(f"Глубина: {difficulty}")
    # for i in range(10):
    while True:
        expr = generate_expression(depth=j)
        try:
            if int(expr.expr) == expr.value:
                pass
        except:
            break
    str_expr = str(expr.expr).replace("/", "∶").replace("*", "×") + " = ?"
    _LOGGER.info(f"Пример: {str_expr} = ?")
    _LOGGER.info(f"Ответ: {expr.value}")
    return str_expr, expr.value
