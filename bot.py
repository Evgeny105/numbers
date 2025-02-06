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
dp = Dispatcher(storage=MemoryStorage())


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
    else:
        await message.answer(
            f"Привет, {hbold(message.from_user.full_name)}! \n"
            f"Сейчас мы с тобой работаем на уровне сложности: {difficulty}"
        )
    # await state.set_state(AuthForm.email)
    # await state.update_data(g_client=g_client)


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


@dp.message(
    (F.document.mime_type == "application/xml")  # MIME-type XML
    | (F.document.file_name.endswith(".tcx"))  # For .tcx
)
async def handle_tcx_file(
    message: Message, bot: Bot, state: FSMContext
) -> None:
    # Log file details
    _LOGGER.info(
        f"Received file: {message.document.file_name}, MIME-type: {message.document.mime_type} "
        f"from user {message.from_user.full_name}, ID={message.from_user.id}"
    )
    if message.document.file_size > 50 * 1024 * 1024:  # 50 MB
        await message.answer(
            "The file is too large. Please send a smaller file."
        )
        return

    data = await state.get_data()
    g_client = data.get("g_client")
    if not g_client:
        g_client = await check_auth(message, bot, state)
        if not g_client:
            return

    # Get file details
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path

    # Download the file into memory
    downloaded_file = await bot.download_file(file_path)
    file_content = downloaded_file.read()
    # Check if the file content is a valid TCX file
    if re.search(rb"<\?xml.*?\?>", file_content) and re.search(
        rb"<TrainingCenterDatabase", file_content
    ):
        try:
            # Convert the TCX file (in memory)
            converted_content, summary = convert_tcx_in_memory(file_content)
            _LOGGER.info("TCX conversion completed successfully.")

            # Send back the converted file
            await message.answer(
                "Conversion was successful! Trying to upload to Garmin Connect....\n\n"
                f"📅 Activity Date & Time: {summary['activity_datetime']}\n"
                f"⏱ Total Time: {summary['total_time']}\n"
                f"🛣 Total Distance: {summary['total_distance_km']} km"
            )
            try:
                converted_content_io = io.BytesIO(converted_content)
                converted_content_io.name = (
                    f"converted_{message.document.file_name}"
                )
                uploaded = g_client.upload(converted_content_io)

                if uploaded:
                    await message.answer(
                        "File uploaded successfully to Garmin Connect!"
                    )
            except garth.exc.GarthHTTPError as e:
                await message.answer_document(
                    BufferedInputFile(
                        converted_content,
                        filename=f"converted_{message.document.file_name}",
                    ),
                    caption="Something is wrong with uploading. Here is your converted TCX file.",
                )

        except Exception as e:
            _LOGGER.error(f"Error during conversion: {e}")
            await message.answer(
                "An error occurred while converting the file. Please try again or another file."
            )
    else:
        await message.answer(
            "The file you sent does not appear to be a valid TCX file."
        )
        _LOGGER.info(
            f"Invalid TCX file received from user {message.from_user.id}."
        )


@dp.message(F.document.file_name.endswith(".fit"))  # For .fit files
async def handle_fit_file(
    message: Message, bot: Bot, state: FSMContext
) -> None:
    # Log file details
    _LOGGER.info(
        f"Received file: {message.document.file_name}, MIME-type: {message.document.mime_type} "
        f"from user {message.from_user.full_name}, ID={message.from_user.id}"
    )
    if message.document.file_size > 50 * 1024 * 1024:  # 50 MB
        await message.answer(
            "The file is too large. Please send a smaller file."
        )
        return

    data = await state.get_data()
    g_client = data.get("g_client")
    if not g_client:
        g_client = await check_auth(message, bot, state)
        if not g_client:
            return

    # Get file details
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path

    # Download the file into memory
    downloaded_file = await bot.download_file(file_path)
    file_content = downloaded_file.read()

    try:
        # Process the FIT file
        app_fit = FitFile.from_bytes(file_content)
        summary = {}
        for record in app_fit.records:
            m = record.message
            if isinstance(m, SessionMessage):
                summary["activity_datetime"] = datetime.fromtimestamp(
                    m.start_time / 1000
                ).strftime("%d %b @ %H:%M UTC")
                total_seconds_rounded = round(m.total_timer_time)
                summary["total_time"] = str(
                    timedelta(seconds=total_seconds_rounded)
                )
                distance_km = float(m.total_distance) / 1000
                summary["total_distance_km"] = f"{distance_km:.2f}"
                break

        _LOGGER.info("FIT processing completed successfully.")

        await message.answer(
            "Trying to upload to Garmin Connect....\n\n"
            f"📅 Activity Date & Time: {summary['activity_datetime']}\n"
            f"⏱ Total Time: {summary['total_time']}\n"
            f"🛣 Total Distance: {summary['total_distance_km']} km"
        )
        try:
            file_content_io = io.BytesIO(file_content)
            file_content_io.name = message.document.file_name
            uploaded = g_client.upload(file_content_io)

            if uploaded:
                await message.answer(
                    "File uploaded successfully to Garmin Connect!"
                )
        except garth.exc.GarthHTTPError as e:
            await message.answer("Something is wrong with uploading")

    except Exception as e:
        _LOGGER.error(f"Error during processing FIT-file: {e}")
        await message.answer(
            "An error occurred while processing the FIT-file. Please try again or another file."
        )


@dp.message(F.document.file_name.endswith(".zip"))
async def handle_zip_file(
    message: Message, bot: Bot, state: FSMContext
) -> None:
    """
    This handler processes ZIP files, extracts TCX files, and sends them back.
    """
    _LOGGER.info(
        f"Received file: {message.document.file_name}, MIME-type: {message.document.mime_type} "
        f"from user {message.from_user.full_name}, ID={message.from_user.id}"
    )
    if message.document.file_size > 50 * 1024 * 1024:  # 50 MB
        await message.answer(
            "The file is too large. Please send a smaller file."
        )
        return

    data = await state.get_data()
    g_client = data.get("g_client")
    if not g_client:
        g_client = await check_auth(message, bot, state)
        if not g_client:
            return

    # Get file details
    file_id = message.document.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path

    # Download the ZIP file into memory
    downloaded_file = await bot.download_file(file_path)
    file_content = downloaded_file.read()

    # Work with the ZIP file in memory
    try:
        with zipfile.ZipFile(io.BytesIO(file_content), "r") as zip_ref:
            for file_name in zip_ref.namelist():
                if file_name.endswith(".tcx"):
                    with zip_ref.open(file_name) as tcx_file:
                        tcx_content = tcx_file.read()
                        try:
                            # Convert the TCX file (in memory)
                            converted_content, summary = convert_tcx_in_memory(
                                tcx_content
                            )

                            # Send back the converted file
                            await message.answer(
                                "Conversion was successful! Trying to upload to Garmin Connect....\n\n"
                                f"📅 Activity Date & Time: {summary['activity_datetime']}\n"
                                f"⏱ Total Time: {summary['total_time']}\n"
                                f"🛣 Total Distance: {summary['total_distance_km']} km"
                            )
                            try:
                                converted_content_io = io.BytesIO(
                                    converted_content
                                )
                                converted_content_io.name = (
                                    f"converted_{file_name}"
                                )
                                uploaded = g_client.upload(converted_content_io)

                                if uploaded:
                                    await message.answer(
                                        "File uploaded successfully to Garmin Connect!"
                                    )
                            except garth.exc.GarthHTTPError as e:
                                await message.answer_document(
                                    BufferedInputFile(
                                        converted_content,
                                        filename=f"converted_{file_name}",
                                    ),
                                    caption="Something is wrong with uploading. Here is your converted TCX file.",
                                )

                        except Exception as e:
                            _LOGGER.error(
                                f"Error during conversion of {tcx_file}: {e}"
                            )
                            await message.answer(
                                f"An error occurred while converting the file {tcx_file}. Please try again."
                            )

    except zipfile.BadZipFile:
        await message.answer(
            "The file you sent is not a valid ZIP file. Please send a valid ZIP archive."
        )
    except Exception as e:
        _LOGGER.error(f"Error processing ZIP file: {e}")
        await message.answer(
            "An unexpected error occurred while processing the ZIP file. Please try again."
        )


@dp.message()
async def echo_handler(message: types.Message) -> None:
    """
    Handler will forward receive a message back to the sender
    By default, message handler will handle all message types (like a text, photo, sticker etc.)
    """
    try:
        # Send a copy of the received message
        await message.answer(
            "Nice try, but I can handle only TCX files for now. Try sending a TCX file instead!"
        )
        # await message.send_copy(chat_id=message.chat.id)
    except TypeError:
        # But not all the types is supported to be copied so need to handle it
        await message.answer("Nice try!")


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
