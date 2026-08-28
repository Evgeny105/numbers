"""Phrase categories and the static fallback text for each.

These are the lines the bot sent before the phrase pool existed. They stay in
the source as the guaranteed floor: if the pool is empty and every LLM provider
is unreachable, the bot still speaks, and it speaks exactly the way it used to.

All of these are shown to a child, so they are deliberately warm and short.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    brief: str
    """What the phrase must convey, handed to the LLM as the generation brief."""


CORRECT_1ST = "correct_1st"
CORRECT_2ND = "correct_2nd"
CORRECT_3RD = "correct_3rd"
WRONG_RETRY = "wrong_retry"
WRONG_FINAL = "wrong_final"
GREETING_NEW = "greeting_new"
GREETING_BACK = "greeting_back"
FAREWELL = "farewell"
INVALID_INPUT = "invalid_input"
LEVEL_UP = "level_up"

CATEGORIES: dict[str, Category] = {
    CORRECT_1ST: Category(
        CORRECT_1ST,
        "Верно с первой попытки",
        "бурная радость и похвала за то, что ребёнок решил пример сразу, с первой попытки",
    ),
    CORRECT_2ND: Category(
        CORRECT_2ND,
        "Верно со второй попытки",
        "радость и похвала за то, что ребёнок решил пример со второй попытки",
    ),
    CORRECT_3RD: Category(
        CORRECT_3RD,
        "Верно с третьей попытки",
        "похвала за упорство: ребёнок решил пример с третьей, последней попытки",
    ),
    WRONG_RETRY: Category(
        WRONG_RETRY,
        "Ошибка, есть ещё попытка",
        "мягкая поддержка: ответ неверный, но попытки ещё есть, стоит проверить и попробовать снова",
    ),
    WRONG_FINAL: Category(
        WRONG_FINAL,
        "Ошибка, попытки кончились",
        "утешение без упрёка: пример не получился, ничего страшного, впереди новый",
    ),
    GREETING_NEW: Category(
        GREETING_NEW,
        "Приветствие нового",
        "тёплое приветствие ребёнка, который впервые пришёл тренировать устный счёт",
    ),
    GREETING_BACK: Category(
        GREETING_BACK,
        "Приветствие вернувшегося",
        "радостное приветствие ребёнка, который вернулся продолжить тренировку",
    ),
    FAREWELL: Category(
        FAREWELL,
        "Прощание",
        "доброе прощание с приглашением возвращаться",
    ),
    INVALID_INPUT: Category(
        INVALID_INPUT,
        "Не число",
        "весёлая просьба прислать именно число, а не буквы или что-то другое",
    ),
    LEVEL_UP: Category(
        LEVEL_UP,
        "Смена уровня",
        "поздравление с тем, что примеры стали сложнее, потому что ребёнок хорошо справляется",
    ),
}

#: A single emoji sent as its own message renders large in Telegram and plays
#: an animation, so a win gets a visible little firework rather than another
#: line of text. Only the celebratory categories get one.
CELEBRATION_EMOJI: dict[str, tuple[str, ...]] = {
    CORRECT_1ST: ("🎉", "🥳", "🔥", "💯", "🏆", "⭐", "🚀", "🎊"),
    CORRECT_2ND: ("🎉", "👍", "😎", "⭐", "🎈", "💪"),
    CORRECT_3RD: ("🎆", "💪", "🏅", "👏", "🎊"),
    LEVEL_UP: ("⚡", "🚀", "📈", "🔥"),
    GREETING_NEW: ("👋",),
    GREETING_BACK: ("👋",),
    FAREWELL: ("👋",),
}


STATIC_PHRASES: dict[str, tuple[str, ...]] = {
    CORRECT_1ST: (
        "🎉 УРА!!! С первой попытки — это точно золотая медаль! 🥇",
        "🤩 Вот это скорость! Ответ верный сразу! 🌟",
        "С первого раза! Ты щёлкаешь примеры как орешки! 🥇",
    ),
    CORRECT_2ND: (
        "🎈 Ура! Получилось! Со второй попытки — это круто! 🥈",
        "Есть! Вторая попытка — и точно в цель! 😎",
        "Отлично, разобрался! Серебряная медалька твоя! 🥈",
    ),
    CORRECT_3RD: (
        "🎆 ФАНФАРЫ! С третьей попытки — это победа! 🏁",
        "Ты не сдался и справился! Настоящий упорный боец! 💥",
        "Получилось! Вот что значит не бросать на полпути! 🥉",
    ),
    WRONG_RETRY: (
        "Ой-ой-ой! 🫢 Кажется, тут маленькая ошибка. Проверь аккуратненько!",
        "Хм-м... 🤔 Опять маленькая помарка. Давай посмотрим внимательнее!",
        "Почти! Ещё разок, ты обязательно справишься! 💪",
    ),
    WRONG_FINAL: (
        "🫂 Не грусти! Этот пример был слишком хитрющим! 🦊",
        "Бывает! Этот пример оказался с характером. Берём новый! 😉",
        "Ничего страшного! Зато теперь ты знаешь, как он решается. 🌈",
    ),
    GREETING_NEW: (
        "Приветик! 🌟 Я твой весёлый помощник в мире вычислений! 🚀",
        "Привет! Давай считать быстро и весело! 🧮",
    ),
    GREETING_BACK: (
        "Снова здравствуй! 🌈 Продолжаем тренировку!",
        "О, ты вернулся! Отлично, начинаем! 🚀",
    ),
    FAREWELL: (
        "Пока-пока! 👋 Возвращайся скорее, будем играть ещё! 🎮",
        "До встречи! Твои успехи я запомнил. 🌟",
    ),
    INVALID_INPUT: (
        "Циферки-циферки! 🔢 Давай только числа, как настоящие математики! 🧮",
        "Мне нужно именно число — давай попробуем ещё раз! 🤗",
    ),
    LEVEL_UP: (
        "Ты так здорово справляешься, что примеры стали посложнее! ⚡️",
        "Новый уровень! Примеры подросли вместе с тобой. 🚀",
    ),
}
