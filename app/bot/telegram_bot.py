import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from config import settings
from app.bot.handlers import router
from app.utils.logger import logger

# Initialize bot with HTML parse mode as default
bot = Bot(
    token=settings.telegram_bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
dp.include_router(router)

async def start_bot():
    """
    Cleans webhook and starts polling the Telegram bot.
    """
    logger.info("Starting Telegram Bot polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        logger.error(
            "❌ Ошибка авторизации Telegram: Неверный или пустой токен бота (TELEGRAM_BOT_TOKEN) в файле .env!\n"
            "   Убедитесь, что вы создали бота через @BotFather и указали правильный токен.\n"
            "   ⚠️ Telegram-бот НЕ БУДЕТ принимать сообщения и отправлять уведомления, но веб-панель аналитики продолжит работу."
        )
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logger.error(
            "❌ Неожиданная ошибка при запуске Telegram-бота: {}\n"
            "   ⚠️ Бот отключен, но веб-панель аналитики продолжит работу.", e
        )
        while True:
            await asyncio.sleep(3600)

