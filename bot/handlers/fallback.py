"""Anything that matched no other handler."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

async def fallback_handler(message: Message) -> None:
    await message.answer(
        "🤖 Я понимаю числовые ответы и команды.\n"
        "Нажми /start, и начнём считать! 🎲"
    )


def build_router() -> Router:
    router = Router(name="fallback")
    router.message.register(fallback_handler)
    return router
