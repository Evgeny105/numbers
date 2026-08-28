"""`/start`, `/stop`, `/help` and grade profile selection."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import quiz, texts
from bot.math.profiles import PROFILES, get_profile
from bot.services.phrase_service import PhraseService
from bot.states import UserStates
from bot.storage.db import Database

_LOGGER = logging.getLogger(__name__)

PROFILE_CALLBACK_PREFIX = "profile:"


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{profile.title} — {profile.description}",
                    callback_data=f"{PROFILE_CALLBACK_PREFIX}{profile.key}",
                )
            ]
            for profile in PROFILES.values()
        ]
    )


async def ask_for_profile(message: Message, state: FSMContext) -> None:
    await state.set_state(UserStates.choosing_profile)
    await message.answer(
        "Выбери, какие примеры тебе подойдут — потом можно поменять командой /level:",
        reply_markup=profile_keyboard(),
    )


async def start_handler(
    message: Message, state: FSMContext, db: Database, phrases: PhraseService
) -> None:
    user = message.from_user
    if user is None:
        return

    progress = await quiz.load_progress(db, user.id)
    name = html.escape(user.full_name)

    if not progress.profile:
        greeting = await phrases.get(texts.GREETING_NEW, user.id)
        await message.answer(f"{greeting.text}\n\nРад знакомству, <b>{name}</b>!")
        await db.record_event(user.id, "session_start", {"kind": "first"})
        await ask_for_profile(message, state)
        return

    greeting = await phrases.get(texts.GREETING_BACK, user.id)
    profile = get_profile(progress.profile)
    await message.answer(
        f"{greeting.text}\n\n<b>{name}</b>, ты на уровне «{profile.title}», "
        f"сложность {progress.difficulty}, баллов {progress.score}."
    )
    await state.set_state(UserStates.awaiting_answer)
    await message.answer(await quiz.issue_problem(state, progress))


async def choose_profile(
    callback: CallbackQuery, state: FSMContext, db: Database
) -> None:
    user = callback.from_user
    key = (callback.data or "").removeprefix(PROFILE_CALLBACK_PREFIX)
    if key not in PROFILES:
        await callback.answer("Такого уровня нет")
        return

    previous = await quiz.load_progress(db, user.id)
    profile = PROFILES[key]
    difficulty = quiz.difficulty_for_score(previous.score, key)
    await db.set_user_fields(user.id, grade_profile=key, difficulty=difficulty)
    await db.record_event(
        user.id, "level_change", {"from": previous.profile or None, "to": key}
    )

    await callback.answer(f"Уровень: {profile.title}")
    if callback.message is not None and isinstance(callback.message, Message):
        await callback.message.edit_text(f"Уровень: <b>{profile.title}</b> — {profile.description}")
        await state.set_state(UserStates.awaiting_answer)
        progress = quiz.UserProgress(profile=key, difficulty=difficulty, score=previous.score)
        await callback.message.answer(await quiz.issue_problem(state, progress))


async def level_handler(message: Message, state: FSMContext) -> None:
    await ask_for_profile(message, state)


async def stop_handler(
    message: Message, state: FSMContext, db: Database, phrases: PhraseService
) -> None:
    user = message.from_user
    if user is None:
        return

    await state.clear()
    await db.close_user_sessions(user.id, reason="stop")
    await db.record_event(user.id, "session_stop", {"kind": "command"})

    farewell = await phrases.get(texts.FAREWELL, user.id)
    await message.answer(
        f"{farewell.text}\n\nТвои успехи я запомнил — /start, и продолжим."
    )
    _LOGGER.info("user %s stopped the session", user.id)


async def help_handler(message: Message) -> None:
    await message.answer(
        "Я помогаю тренировать устный счёт.\n\n"
        "/start — начать или продолжить\n"
        "/level — выбрать уровень примеров\n"
        "/stop — закончить\n"
        "/help — эта справка"
    )


def build_router() -> Router:
    """A fresh router. Router objects bind to one parent, so never share one."""
    router = Router(name="start")
    router.message.register(start_handler, CommandStart())
    router.message.register(level_handler, Command("level"))
    router.message.register(stop_handler, Command("stop"))
    router.message.register(help_handler, Command("help"))
    router.callback_query.register(choose_profile, F.data.startswith(PROFILE_CALLBACK_PREFIX))
    return router
