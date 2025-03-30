import asyncio
import datetime
import io
import logging
import re
from datetime import datetime, timedelta
from itertools import repeat
from os import getenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.methods import SendMessage
from aiogram.types import BufferedInputFile, Message
from aiogram.utils.markdown import hbold

from gen import generate
from redis_handlers import init_redis
from states import UserStates

# Set up logging
LOG_LEVEL = getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
_LOGGER = logging.getLogger(__name__)

# Initialize the Bot and Dispatcher
TOKEN_API = getenv("TOKEN_API_BOT")
try:
    storage: RedisStorage = init_redis()
except Exception as e:
    _LOGGER.error(f"Redis initialization failed: {e}")
    storage = MemoryStorage()
    _LOGGER.warning("Using MemoryStorage instead of Redis")
dp = Dispatcher(storage=storage)


# Concurently version of the message.answer method
async def message_answer(message: Message, text: str) -> SendMessage:
    return await message.answer(text)


async def add_points(state: FSMContext) -> None:
    try:
        data = await state.get_data()
        points = data.get("points", 0)
        user_name = data.get("user_name", "Unknown")
        points += 1
        points = min(points, 49)
        points = max(points, 0)
        difficulty = points // 10
        _LOGGER.info(
            f"Пользователь {user_name} справился и получил {points} баллов."
        )
        asyncio.create_task(
            state.update_data(difficulty=difficulty, points=points)
        )
    except:
        _LOGGER.error("Ошибка при добавлении баллов")
        asyncio.create_task(state.update_data(difficulty=0, points=0))


async def subtract_points(state: FSMContext) -> None:
    try:
        data = await state.get_data()
        points = data.get("points", 1)
        user_name = data.get("user_name", "Unknown")
        points -= 1
        points = min(points, 49)
        points = max(points, 0)
        difficulty = points // 10
        _LOGGER.info(
            f"Пользователь {user_name} не справился и получил {points} баллов."
        )
        asyncio.create_task(
            state.update_data(difficulty=difficulty, points=points)
        )
    except:
        _LOGGER.error("Ошибка при вычитании баллов")
        asyncio.create_task(state.update_data(difficulty=0, points=0))


async def get_new_task(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    difficulty = data.get("difficulty", 0)
    expression, answer = generate(difficulty)
    asyncio.create_task(
        state.update_data(
            expression=expression,
            answer=answer,
            user_name=message.from_user.full_name,
        )
    )
    asyncio.create_task(
        message_answer(
            message,
            "🔔 Внимание-внимание! Новый примерчик! 🔔\n"
            f"<code>{expression}</code>\n"
            "Скорее пиши ответ! ⏱️",
        )
    )
    asyncio.create_task(state.set_state(UserStates.await_1_answer))


@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    difficulty = data.get("difficulty")
    if difficulty is None:
        await message_answer(
            message,
            f"Приветик, {hbold(message.from_user.full_name)}! 🌟\n"
            "Я твой весёлый помощник в мире вычислений! 🚀\n\n"
            "Давай начнём с простеньких примеров, а если ты будешь щёлкать их как орешки, "
            "я подкину тебе задачки посложнее! 😉\n"
            "Со мной будешь суперзвездой математики! 💫",
        )
        asyncio.create_task(state.update_data(difficulty=0))
        _LOGGER.info(
            f"Новый пользователь: {message.from_user.full_name}, id: {message.from_user.id}"
        )
    else:
        await message_answer(
            message,
            f"Снова здравствуй, {hbold(message.from_user.full_name)}! 🌈\n"
            f"Сейчас мы с тобой на уровне сложности: {difficulty} ⚡️",
        )
        _LOGGER.info(
            f"Повторный запуск: {message.from_user.full_name}, id: {message.from_user.id}"
        )
    asyncio.create_task(
        state.update_data(user_name=message.from_user.full_name)
    )
    asyncio.create_task(get_new_task(message, state))


@dp.message(Command("stop"))
async def stop_handler(message: Message, state: FSMContext) -> None:
    try:
        await state.clear()
    finally:
        asyncio.create_task(
            message_answer(
                message,
                f"Пока-пока, {hbold(message.from_user.full_name)}! 👋\n"
                "Я бережно записываю твои успехи... шучу, забыл всё! 🤫\n"
                "Возвращайся скорее, будем играть ещё! 🎮",
            )
        )
        _LOGGER.info(
            f"Пользователь {message.from_user.full_name} завершил работу с ботом"
        )


@dp.message(UserStates.await_1_answer)
async def answer1_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        ans = message.text.replace(" ", "").replace(",", ".").replace("=", "-")
        ans = float(ans)
        right_answer = data.get("answer")
        if ans == right_answer:

            messages = [
                "🤩",
                "🎉 УРА!!! 🎉",
                "С ПЕРВОЙ попытки! 🌟\nЭто точно золотая медаль! 🥇",
            ]
            await asyncio.gather(
                *map(message_answer, repeat(message), messages)
            )
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} решил пример с первой попытки"
            )
            await add_points(state)
            asyncio.create_task(get_new_task(message, state))
        else:
            asyncio.create_task(
                message_answer(
                    message,
                    "Ой-ой-ой! 🫢\n"
                    "Кажется, тут маленькая ошибка! 🧐\n"
                    "Проверь аккуратненько и попробуй ещё раз!\n"
                    "Вот наш пример:\n"
                    f"<code>{data.get('expression')}</code>\n"
                    "Ты обязательно справишься! 💪",
                )
            )
            asyncio.create_task(state.set_state(UserStates.await_2_answer))
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} ошибся первый раз"
            )
    except:
        asyncio.create_task(
            message_answer(
                message,
                "Циферки-циферки! 🔢\n"
                "Давай только числа, как настоящие математики! 🧮\n"
                "Попробуй ещё разок! 😊\n"
                "Вот наш пример:\n"
                f"<code>{data.get('expression')}</code>\n",
            )
        )
        return


@dp.message(UserStates.await_2_answer)
async def answer2_handler(message: Message, state: FSMContext) -> None:
    ans = message.text.replace(" ", "").replace(",", ".").replace("=", "-")
    data = await state.get_data()
    try:
        ans = float(ans)
        right_answer = data.get("answer")
        if ans == right_answer:
            await message_answer(
                message,
                "🎈 Ура! Получилось! 🎈\n"
                "Со второй попытки - это круто! 😎\n"
                "Твоя награда - серебряная медалька! 🥈",
            )
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} решил пример со второй попытки"
            )
            await add_points(state)
            asyncio.create_task(get_new_task(message, state))
        else:
            await message_answer(
                message,
                "Хм-м... 🤔\n"
                "Опять маленькая помарка! 🎨\n"
                "Давай посмотрим внимательнее:\n"
                f"<code>{data.get('expression')}</code>\n"
                "Ты почти у цели! 🌈",
            )
            asyncio.create_task(state.set_state(UserStates.await_3_answer))
    except:
        asyncio.create_task(
            message_answer(
                message,
                "Ой, это что ли буквы?... а надо цифры! 🔤➡️🔢\n"
                "Попробуй написать просто число, как мы договаривались! 🤝\n"
                "Вот наш пример:\n"
                f"<code>{data.get('expression')}</code>\n",
            )
        )
        return


@dp.message(UserStates.await_3_answer)
async def answer3_handler(message: Message, state: FSMContext) -> None:
    ans = message.text.replace(" ", "").replace(",", ".").replace("=", "-")
    data = await state.get_data()
    try:
        ans = float(ans)
        reight_answer = data.get("answer")
        if ans == reight_answer:
            await message_answer(
                message,
                "🎆 ФАНФАРЫ! 🎇\n"
                "С третьей попытки - это победа! 🏁\n"
                "Ты настоящий упорный боец! 💥",
            )
            await add_points(state)
            asyncio.create_task(get_new_task(message, state))
        else:
            await message_answer(message, "🫂 Не грусти!")
            await message_answer(
                message,
                "Этот пример был слишком хитрющим! 🦊\n"
                f"Правильный ответ: <b>{reight_answer}</b>\n"
                "Давай возьмём новый пример - он точно по зубам! 😉\n"
                "Уже бегу искать... 🏃",
            )
            await subtract_points(state)
            asyncio.create_task(get_new_task(message, state))
    except:
        asyncio.create_task(
            message_answer(
                message,
                "Кажется, кто-то хочет поиграть в загадки? 🎭\n"
                "Но мне нужно именно число - давай попробуем ещё раз! 🤗\n"
                "Вот наш пример:\n"
                f"<code>{data.get('expression')}</code>\n",
            )
        )
        return


@dp.message()
async def echo_handler(message: types.Message) -> None:
    asyncio.create_task(
        message_answer(
            message,
            "🤖 Я понимаю только числовые ответы, давай играть! 🎲\nДля начала используй команду /start",
        )
    )


async def main() -> None:
    # Initialize Bot instance with a default parse mode which will be passed to all API calls
    bot = Bot(
        TOKEN_API, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    try:
        # Start polling for updates
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
