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
        ("Реши-ка вот такой пример: \n" f"<code>{expression}</code>")
    )
    await state.set_state(UserStates.await_1_answer)


@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    """
    This handler receives messages with /start command.
    """
    data = await state.get_data()
    difficulty = data.get("difficulty")
    if difficulty is None:
        await message.answer(
            f"Привет, {hbold(message.from_user.full_name)}! \n"
            "Я твой помощник в улучшении оценок по математике 😜\n\n"
            "Сейчас для тебя будут придумываться примеры простого уровня, но если они окажутся слишком простыми, то я подстроюсь под твой уровень 😉"
        )
        await state.update_data(difficulty=0)
        _LOGGER.info(
            f"Новый пользователь: {message.from_user.full_name}, id: {message.from_user.id}"
        )
    else:
        await message.answer(
            f"Привет, {hbold(message.from_user.full_name)}! \n"
            f"Сейчас мы с тобой работаем на уровне сложности: {difficulty}"
        )
        _LOGGER.info(
            f"Повторный запуск: {message.from_user.full_name}, id: {message.from_user.id}"
        )
    # await state.set_state(UserStates.solved)
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
            await message.answer(
                "Вау! Верно с первой попытки! 😎\n Это на 5 с плюсом!"
            )
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} решил пример с первой попытки"
            )
            await add_points(state)
            await get_new_task(message, state)
        else:
            await message.answer(
                (
                    "Нет, это не верно 😢\n"
                    "Проверь свои вычисления и попробуй еще раз, у тебя всё получится!\n"
                    "Повторяю пример:\n"
                    f"<code>{data.get('expression')}</code>\n"
                )
            )
            await state.set_state(UserStates.await_2_answer)
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} ошибся первый раз"
            )
    except:
        await message.answer(
            "Это все конечно хорошо, но в ответ мне нужны только цифры 😋"
        )
        _LOGGER.info(
            f"Пользователь {message.from_user.full_name} написал не цифры в ответ"
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
                "Верно со второй попытки! 😎\n Это на 4 с плюсом!"
            )
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} решил пример со второй попытки"
            )
            await add_points(state)
            await get_new_task(message, state)
        else:
            await message.answer(
                (
                    "К сожалению, это не верно 😢\n"
                    "Проверь еще раз где-то спряталась ошибка ты её найдешь и мы победим!\n"
                    "Повторяю пример:\n"
                    f"<code>{data.get('expression')}</code>\n"
                )
            )
            await state.set_state(UserStates.await_3_answer)
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} ошибся второй раз"
            )
    except:
        await message.answer(
            "Это все конечно хорошо, но в ответ мне нужны только цифры 😋"
        )
        _LOGGER.info(
            f"Пользователь {message.from_user.full_name} написал не цифры в ответ"
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
                "Верно с третьей попытки! 😎\n Ура! Это так здорово что у тебя получилось! 🎆🎆🎆"
            )
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} решил пример с третьей попытки"
            )
            await add_points(state)
            await get_new_task(message, state)
        else:
            await message.answer(("😢"))
            await message.answer(
                "Похоже это очень трудный для тебя пример?\n"
                f"Не расстраивайся, верный ответ был: <b>{reight_answer}</b>\n"
                "Давай попробуем другой..."
            )
            _LOGGER.info(
                f"Пользователь {message.from_user.full_name} ошибся третий раз и получил новый пример"
            )
            await subtract_points(state)
            await get_new_task(message, state)
            await state.set_state(UserStates.await_1_answer)
    except:
        await message.answer(
            "Это все конечно хорошо, но в ответ мне нужны только цифры 😋"
        )
        _LOGGER.info(
            f"Пользователь {message.from_user.full_name} написал не цифры в ответ"
        )
        return


@dp.message(Command("stop"))
async def stop_handler(message: Message, state: FSMContext) -> None:
    """
    This handler receives messages with /stop command.
    """
    try:
        await state.clear()
    finally:
        await message.answer(
            f"Пока, {hbold(message.from_user.full_name)}... \n"
            "Я забыл все данные о тебе... \n 😢"
        )


@dp.message()
async def echo_handler(message: types.Message) -> None:
    """
    By default, message handler will handle all message types (like a text, photo, sticker etc.)
    """
    await message.answer("😋")


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
