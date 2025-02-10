import asyncio
import datetime
import io
import logging
import re
from datetime import datetime, timedelta
from os import getenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BufferedInputFile, Message
from aiogram.utils.markdown import hbold

from redis_handlers import init_redis
from states import UserStates
from gen import generate

# Set up logging
logging.basicConfig(level=logging.INFO)
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
        await state.update_data(difficulty=difficulty, points=points)
    except:
        _LOGGER.error("Ошибка при добавлении баллов")
        await state.update_data(difficulty=0, points=0)


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
        await state.update_data(difficulty=difficulty, points=points)
    except:
        _LOGGER.error("Ошибка при вычитании баллов")
        await state.update_data(difficulty=0, points=0)


async def get_new_task(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    difficulty = data.get("difficulty")
    expression, answer = generate(difficulty)
    await state.update_data(
        expression=expression,
        answer=answer,
        user_name=message.from_user.full_name,
    )
    await message.answer(
        "🔔 Внимание-внимание! Новый примерчик! 🔔\n"
        f"<code>{expression}</code>\n"
        "Скорее пиши ответ! ⏱️"
    )
    await state.set_state(UserStates.await_1_answer)


@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    difficulty = data.get("difficulty")
    if difficulty is None:
        await message.answer(
            f"Приветик, {hbold(message.from_user.full_name)}! 🌟\n"
            "Я твой весёлый помощник в мире цифр и примеров! 🚀\n\n"
            "Давай начнём с простеньких примеров, а если ты будешь щёлкать их как орешки, "
            "я подкину тебе задачки посложнее! 😉\n"
            "Готов стать суперзвездой математики? 💫"
        )
        await state.update_data(difficulty=0)
        _LOGGER.info(
            f"Новый пользователь: {message.from_user.full_name}, id: {message.from_user.id}"
        )
    else:
        await message.answer(
            f"Снова здравствуй, {hbold(message.from_user.full_name)}! 🌈\n"
            f"Сейчас мы играем на уровне сложности: {difficulty} ⚡️"
        )
        _LOGGER.info(
            f"Повторный запуск: {message.from_user.full_name}, id: {message.from_user.id}"
        )
    await state.update_data(user_name=message.from_user.full_name)
    await get_new_task(message, state)


@dp.message(UserStates.await_1_answer)
async def answer1_handler(message: Message, state: FSMContext) -> None:
    ans = message.text.replace(" ", "").replace(",", ".").replace("=", "-")
    try:
        ans = float(ans)
        data = await state.get_data()
        right_answer = data.get("answer")
        if ans == right_answer:
            await message.answer(("🤩"))
            await message.answer(("🎉 УРА!!! 🎉"))
            await message.answer(
                "Ты справился с ПЕРВОЙ попытки! 🌟\n"
                "Это точно золотая медаль! 🏆\n"
                "Следующий уровень через... щас придумаю! 😄"
            )
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} решил пример с первой попытки"
            )
            await add_points(state)
            await get_new_task(message, state)
        else:
            await message.answer(
                "Ой-ой-ой! 🫢\n"
                "Кажется, тут маленькая ошибка! 🧐\n"
                "Проверь аккуратненько и попробуй ещё раз!\n"
                "Вот наш пример:\n"
                f"<code>{data.get('expression')}</code>\n"
                "Ты обязательно справишься! 💪"
            )
            await state.set_state(UserStates.await_2_answer)
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} ошибся первый раз"
            )
    except:
        await message.answer(
            "Циферки-циферки! 🔢\n"
            "Давай только числа, как настоящие математики! 🧮\n"
            "Попробуй ещё разок! 😊"
        )
        return


@dp.message(UserStates.await_2_answer)
async def answer2_handler(message: Message, state: FSMContext) -> None:
    ans = message.text.replace(" ", "").replace(",", ".").replace("=", "-")
    try:
        ans = float(ans)
        data = await state.get_data()
        reight_answer = data.get("answer")
        if ans == reight_answer:
            await message.answer(
                "🎈 Ура! Получилось! 🎈\n"
                "Со второй попытки - это круто! 😎\n"
                "Твоя награда - серебряная звёздочка! ⭐️"
            )
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} решил пример со второй попытки"
            )
            await add_points(state)
            await get_new_task(message, state)
        else:
            await message.answer(
                "Хм-м... 🤔\n"
                "Опять маленькая помарка! 🎨\n"
                "Давай посмотрим внимательнее:\n"
                f"<code>{data.get('expression')}</code>\n"
                "Ты почти у цели! 🌈"
            )
            await state.set_state(UserStates.await_3_answer)
    except:
        await message.answer(
            "Вижу буквы... а надо цифры! 🔤➡️🔢\n"
            "Попробуй написать просто число, как мы договаривались! 🤝"
        )
        return


@dp.message(UserStates.await_3_answer)
async def answer3_handler(message: Message, state: FSMContext) -> None:
    ans = message.text.replace(" ", "").replace(",", ".").replace("=", "-")
    try:
        ans = float(ans)
        data = await state.get_data()
        reight_answer = data.get("answer")
        if ans == reight_answer:
            await message.answer(
                "🎆 ФАНФАРЫ! 🎇\n"
                "С третьей попытки - это победа! 🏁\n"
                "Ты настоящий упорный боец! 💥"
            )
            await add_points(state)
            await get_new_task(message, state)
        else:
            await message.answer(("🫂 Не грусти!"))
            await message.answer(
                "Этот пример был слишком хитрющим! 🦊\n"
                f"Правильный ответ: <b>{reight_answer}</b>\n"
                "Давай возьмём новый пример - он точно по зубам! 😉\n"
                "Уже бегу искать... 🏃♂️"
            )
            await subtract_points(state)
            await get_new_task(message, state)
    except:
        await message.answer(
            "Кажется, кто-то хочет поиграть в загадки? 🎭\n"
            "Но мне нужно именно число - давай попробуем ещё раз! 🤗"
        )
        return


@dp.message(Command("stop"))
async def stop_handler(message: Message, state: FSMContext) -> None:
    try:
        await state.clear()
    finally:
        await message.answer(
            f"Пока-пока, {hbold(message.from_user.full_name)}! 👋\n"
            "Я бережно записываю твои успехи... шучу, забыл всё! 🤫\n"
            "Возвращайся скорее, будем играть ещё! 🎮"
        )


@dp.message()
async def echo_handler(message: types.Message) -> None:
    await message.answer(
        "🤖 Я понимаю только числовые ответы, давай играть! 🎲"
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
