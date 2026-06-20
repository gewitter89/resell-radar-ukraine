import json
import os
import asyncio
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import settings
from app.storage.database import db_session
from app.storage.models import UserFeedback, Ad
from app.storage.repositories import AdRepository, FeedbackRepository, CategoryStatsRepository
from app.services.learning import apply_feedback_learning, set_pause_state
from app.services.profit_tracker import get_stats_text, get_profit_text, get_top_categories_text
from app.services.monitor import load_watchlist
from app.utils.money import clean_price, format_price
from app.utils.logger import logger
from app.olx.chat_service import OLXChatService
from app.services.ai_learning import record_prediction, record_outcome, get_accuracy_stats
from aiogram.utils.keyboard import InlineKeyboardBuilder

WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "watchlist.json",
)

class WatchlistState(StatesGroup):
    waiting_for_suggest_confirm = State()

router = Router()

class SellState(StatesGroup):
    waiting_for_buy_price = State()
    waiting_for_sell_price = State()

class OLXMessageState(StatesGroup):
    waiting_for_message = State()
    waiting_for_offer_price = State()

async def check_auth(message: Message) -> bool:
    """
    Checks if the user matches the configured chat ID.
    If unauthorized, notifies them with their current chat ID for easy configuration.
    """
    if message.chat.id != settings.telegram_chat_id:
        logger.warning("Unauthorized access attempt from Chat ID: {}", message.chat.id)
        # Reply with their Chat ID so they can set it in .env
        await message.answer(
            f"❌ Доступ ограничен.\n\n"
            f"Ваш Chat ID: <code>{message.chat.id}</code>\n"
            f"Укажите его в файле <code>.env</code> в переменной <code>TELEGRAM_CHAT_ID</code>.",
            parse_mode="HTML"
        )
        return False
    return True

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not await check_auth(message):
        return
        
    await message.answer(
        "👋 <b>Добро пожаловать в Resell Radar Ukraine!</b>\n\n"
        "Я буду мониторить OLX Украина в реальном времени, находить самые выгодные предложения "
        "для перепродажи и присылать их прямо сюда.\n\n"
        "Используйте /help, чтобы увидеть список доступных команд."
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    if not await check_auth(message):
        return
        
    await message.answer(
        "📚 <b>Команды Resell Radar:</b>\n\n"
        "⚡ <b>Мониторинг:</b>\n"
        "/pause — Временно остановить мониторинг объявлений\n"
        "/resume — Возобновить мониторинг\n"
        "/watchlist — Показать список отслеживаемых товаров\n"
        "/watchlist_suggest — AI подберёт новый товар\n"
        "/watchlist_remove — Удалить товар\n"
        "/watchlist_health — Здоровье watchlist\n"
        "/watchlist_top — Топ категорий по успешности\n\n"
        "📈 <b>Аналитика и прибыль:</b>\n"
        "/stats — Показать общую статистику по объявлениям\n"
        "/profit — Показать общую прибыль и ROI\n"
        "/top — Топ категорий по прибыльности\n"
        "/ai_stats — Точность предсказаний AI\n\n"
        "🔄 <b>Карточка сделки (кнопки):</b>\n"
        "Купил / Интересно / Мусор — обратная связь\n"
        "Продал — зафиксировать прибыль\n"
        "Пересканировать — перепарсить заново через Playwright"
    )

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not await check_auth(message):
        return
    text = await asyncio.to_thread(get_stats_text)
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("profit"))
async def cmd_profit(message: Message):
    if not await check_auth(message):
        return
    text = await asyncio.to_thread(get_profit_text)
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("top"))
async def cmd_top(message: Message):
    if not await check_auth(message):
        return
    text = await asyncio.to_thread(get_top_categories_text)
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("watchlist"))
async def cmd_watchlist(message: Message):
    if not await check_auth(message):
        return
    watchlist = load_watchlist()
    if not watchlist:
        await message.answer("Ваш watchlist пуст.")
        return
        
    lines = ["📋 <b>Отслеживаемые товары:</b>", ""]
    for item in watchlist:
        normal = item.get("normal_price_range", [0, 0])
        lines.append(
            f"• <b>{item['name']}</b> ({item['category']})\n"
            f"  Зеленая цена: до {format_price(item['max_green_price'])}\n"
            f"  Рынок: {format_price(normal[0])}–{format_price(normal[1])}\n"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")

@router.message(Command("watchlist_suggest"))
async def cmd_watchlist_suggest(message: Message, state: FSMContext):
    """AI генерирует конфиг для нового товара."""
    if not await check_auth(message):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🤖 <b>AI-подбор товара для мониторинга</b>\n\n"
            "Пример: <code>/watchlist_suggest iPhone 16</code>\n"
            "Бот проанализирует рынок и предложит готовый конфиг.",
            parse_mode="HTML"
        )
        return

    product = parts[1].strip()
    status_msg = await message.answer(f"🔍 Анализирую рынок для <b>{product}</b>...", parse_mode="HTML")

    try:
        from app.web.web_server import _call_deepseek_suggest, _call_gemini_suggest
        result = await _call_deepseek_suggest(product)
        if not result:
            result = await _call_gemini_suggest(product)
        if not result:
            await status_msg.edit_text("❌ Не удалось получить данные от ИИ. Проверьте API ключи.")
            return

        text = (
            f"🤖 <b>AI-анализ для: {product}</b>\n\n"
            f"📦 <b>Название:</b> {result.get('name', product)}\n"
            f"📂 <b>Категория:</b> {result.get('category', 'other')}\n"
            f"💰 <b>Зеленая цена:</b> {format_price(result.get('max_green_price', 0))}\n"
            f"📊 <b>Рынок:</b> {format_price(result.get('normal_price_range_min', 0))} – {format_price(result.get('normal_price_range_max', 0))}\n"
            f"💵 <b>Мин. прибыль:</b> {format_price(result.get('min_profit', 500))}\n"
            f"🔑 <b>Ключевые слова:</b> {', '.join(result.get('keywords', []))}\n"
            f"🚫 <b>Стоп-слова:</b> {', '.join(result.get('bad_words', [])[:5])}...\n\n"
            f"📝 <b>Обоснование:</b> {result.get('reasoning', 'Нет данных')}"
        )

        await state.update_data(suggested=result, product_name=product)
        await state.set_state(WatchlistState.waiting_for_suggest_confirm)
        await status_msg.edit_text(text, parse_mode="HTML")
        await message.answer("❓ Добавить этот товар в watchlist? (да/нет или /cancel)")

    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {e}")

@router.message(WatchlistState.waiting_for_suggest_confirm)
async def confirm_watchlist_suggest(message: Message, state: FSMContext):
    if message.chat.id != settings.telegram_chat_id:
        return
    if message.text.strip().lower() in ("да", "yes", "y", "+", "ок"):
        data = await state.get_data()
        sug = data.get("suggested", {})
        fallback_name = data.get("product_name", sug.get("name", "product"))
        price_range = [sug.get("normal_price_range_min", 0), sug.get("normal_price_range_max", 0)]
        new_item = {
            "id": sug.get("id", fallback_name.lower().replace(" ", "_")),
            "name": sug.get("name", fallback_name),
            "category": sug.get("category", "other"),
            "search_url": f"https://www.olx.ua/uk/{sug.get('olx_category_path', 'list')}/q-{sug.get('search_query', '')}/",
            "keywords": sug.get("keywords", []),
            "bad_words": sug.get("bad_words", []),
            "max_green_price": sug.get("max_green_price", 0),
            "normal_price_range": price_range,
            "min_profit": sug.get("min_profit", 500),
        }
        watchlist = load_watchlist()
        if any(w["id"] == new_item["id"] for w in watchlist):
            await message.answer(f"❌ Товар <b>{new_item['name']}</b> уже есть в watchlist!", parse_mode="HTML")
        else:
            watchlist.append(new_item)
            with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
                json.dump(watchlist, f, indent=2, ensure_ascii=False)
            await message.answer(
                f"✅ <b>{new_item['name']}</b> добавлен в watchlist!\n"
                f"Бот начнёт мониторинг в течение 10 минут.",
                parse_mode="HTML"
            )
    else:
        await message.answer("❌ Отменено")
    await state.clear()

@router.message(Command("watchlist_remove"))
async def cmd_watchlist_remove(message: Message):
    if not await check_auth(message):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: <code>/watchlist_remove &lt;id&gt;</code>\nID можно посмотреть в /watchlist", parse_mode="HTML")
        return
    item_id = parts[1].strip()
    watchlist = load_watchlist()
    new_list = [w for w in watchlist if w["id"] != item_id]
    if len(new_list) == len(watchlist):
        await message.answer(f"❌ Товар с ID <b>{item_id}</b> не найден", parse_mode="HTML")
        return
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(new_list, f, indent=2, ensure_ascii=False)
    await message.answer(f"✅ Товар <b>{item_id}</b> удалён из watchlist", parse_mode="HTML")

@router.message(Command("watchlist_top"))
async def cmd_watchlist_top(message: Message):
    """Показывает топ категорий по успешности."""
    if not await check_auth(message):
        return
    from app.services.watchlist_health import get_top_categories
    
    def get_cats():
        with db_session() as session:
            return get_top_categories(session)
            
    cats = await asyncio.to_thread(get_cats)
    if not cats:
        await message.answer("📊 Данных пока нет. Начните мониторинг!")
        return
    lines = ["🏆 <b>Рейтинг категорий (успешность):</b>", ""]
    for i, c in enumerate(cats[:10], 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "  ")
        lines.append(f"{medal} <b>{c['category'].capitalize()}</b> — score {c['score']} (найдено {c['total']}, куплено {c['bought']}, мусор {c['trash']})")
    await message.answer("\n".join(lines), parse_mode="HTML")

@router.message(Command("ai_stats"))
async def cmd_ai_stats(message: Message):
    if not await check_auth(message):
        return
        
    def get_stats():
        with db_session() as session:
            return get_accuracy_stats(session)
            
    stats = await asyncio.to_thread(get_stats)
    text = (
        f"🤖 <b>AI статистика точности</b>\n\n"
        f"📊 Всего предсказаний: {stats['total_predictions']}\n"
        f"✅ С подтверждением: {stats['with_outcome']}\n"
        f"🎯 Точных: {stats['accurate']} ({stats['accuracy_rate']}%)\n"
        f"📐 Средняя точность цены: {stats['avg_price_accuracy']}%\n\n"
        f"Чем больше данных, тем умнее AI! "
        f"Отмечайте 'Купил' и 'Продал' чтобы AI учился."
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("watchlist_health"))
async def cmd_watchlist_health(message: Message):
    """Показывает статистику по каждой позиции: сколько найдено/отправлено/куплено."""
    if not await check_auth(message):
        return
    watchlist = load_watchlist()

    def fetch_health():
        with db_session() as session:
            results = []
            for item in watchlist:
                wid = item["id"]
                total = session.query(Ad).filter(Ad.watch_item_id == wid).count()
                sent = session.query(Ad).filter(Ad.watch_item_id == wid, Ad.sent_to_telegram == True).count()
                bought = session.query(Ad).join(UserFeedback).filter(
                    Ad.watch_item_id == wid, UserFeedback.action == "bought"
                ).count()
                trash = session.query(Ad).join(UserFeedback).filter(
                    Ad.watch_item_id == wid, UserFeedback.action == "trash"
                ).count()
                results.append((item, total, sent, bought, trash))
            return results

    health_data = await asyncio.to_thread(fetch_health)
    
    lines = ["📊 <b>Здоровье watchlist:</b>", ""]
    for item, total, sent, bought, trash in health_data:
        if total == 0:
            status = "🆕 Новый"
        elif bought >= 2:
            status = "⭐ Золотой"
        elif trash > sent / 2:
            status = "⚠️ Мусорный — скоро будет приостановлен"
        elif sent > 0:
            status = "✅ Работает"
        else:
            status = "⏳ В процессе"

        lines.append(
            f"• <b>{item['name']}</b>\n"
            f"  Статус: {status}\n"
            f"  Найдено: {total} | Отправлено: {sent} | Куплено: {bought} | Мусор: {trash}\n"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")

@router.message(Command("pause"))
async def cmd_pause(message: Message):
    if not await check_auth(message):
        return
    set_pause_state(True)
    await message.answer("⏸ Мониторинг OLX успешно приостановлен.")

@router.message(Command("resume"))
async def cmd_resume(message: Message):
    if not await check_auth(message):
        return
    set_pause_state(False)
    await message.answer("▶ Мониторинг OLX возобновлен.")

@router.message(Command("token"))
async def cmd_token(message: Message):
    if not await check_auth(message):
        return
        
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        has_token = bool(settings.olx_bearer_token)
        status_text = "🟢 Подключен" if has_token else "🔴 Не настроен"
        
        instruction = (
            f"🔑 <b>Настройка авторизации OLX:</b>\n\n"
            f"Для отправки сообщений прямо из Telegram необходимо указать Bearer токен авторизации OLX.\n\n"
            f"<b>Как получить токен:</b>\n"
            f"1. Войдите в свой аккаунт на сайте <b>olx.ua</b>\n"
            f"2. Откройте панель разработчика (клавиша F12) -> вкладка Network (Сеть)\n"
            f"3. Найдите любой запрос к API (например, <code>chats</code> или <code>users</code>)\n"
            f"4. Скопируйте значение заголовка <code>Authorization: Bearer &lt;токен&gt;</code>\n"
            f"5. Отправьте боту команду:\n"
            f"<code>/token &lt;ваш_токен&gt;</code>\n\n"
            f"Текущий статус: <b>{status_text}</b>"
        )
        await message.answer(instruction, parse_mode="HTML")
        return
        
    token = parts[1].strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
        
    status_msg = await message.answer("⏳ Проверка токена через OLX API...")
    
    success, user_info = await OLXChatService.verify_token(token)
    if success:
        OLXChatService.update_token(token)
        await status_msg.edit_text(
            f"✅ <b>Токен успешно сохранен!</b>\n\n"
            f"Аккаунт OLX: <code>{user_info}</code>",
            parse_mode="HTML"
        )
    else:
        await status_msg.edit_text(f"❌ <b>Ошибка проверки токена:</b>\n{user_info}", parse_mode="HTML")

# --- Callback Query Handlers ---

@router.callback_query(F.data.startswith("deal:"))
async def handle_deal_callback(callback: CallbackQuery, state: FSMContext):
    if callback.message.chat.id != settings.telegram_chat_id:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
        
    parts = callback.data.split(":")
    action = parts[1]
    ad_id = int(parts[2])
    
    # Check if ad exists
    def get_ad_initial():
        with db_session() as session:
            ad = AdRepository.get_by_id(session, ad_id)
            if ad:
                return ad.category, ad.watch_item_id
            return None
            
    ad_info = await asyncio.to_thread(get_ad_initial)
    if not ad_info:
        await callback.answer("❌ Объявление не найдено в базе", show_alert=True)
        return
        
    category, watch_item_id = ad_info
        
    if action == "interesting":
        def do_interesting():
            with db_session() as session:
                feedback = UserFeedback(ad_id=ad_id, action="interesting")
                FeedbackRepository.add(session, feedback)
                ad_obj = AdRepository.get_by_id(session, ad_id)
                if ad_obj:
                    ad_obj.status = "interesting"
                    
        await asyncio.to_thread(do_interesting)
        apply_feedback_learning(category, watch_item_id, "interesting")
        await callback.answer("👀 Сохранено в интересные")
        await callback.message.reply("📝 Объявление отмечено как интересное. Бот учтет это при оценке.")
        
    elif action == "trash":
        def do_trash():
            with db_session() as session:
                feedback = UserFeedback(ad_id=ad_id, action="trash")
                FeedbackRepository.add(session, feedback)
                ad_obj = AdRepository.get_by_id(session, ad_id)
                if ad_obj:
                    ad_obj.status = "trash"
                CategoryStatsRepository.increment_stats(session, category, trash=1)
                
        await asyncio.to_thread(do_trash)
        apply_feedback_learning(category, watch_item_id, "trash")
        await callback.answer("❌ Помечено как мусор")
        await callback.message.reply("🗑 Товар отмечен как мусор. Порог deal_score для этой категории повышен.")
        
    elif action == "bought":
        def do_bought():
            with db_session() as session:
                feedback = UserFeedback(ad_id=ad_id, action="bought")
                FeedbackRepository.add(session, feedback)
                ad_obj = AdRepository.get_by_id(session, ad_id)
                if ad_obj:
                    ad_obj.status = "bought"
                CategoryStatsRepository.increment_stats(session, category, bought=1)
                record_outcome(session, ad_id, "bought")
                
        await asyncio.to_thread(do_bought)
        apply_feedback_learning(category, watch_item_id, "bought")
        await callback.answer("✅ Отмечено как купленное")
        await callback.message.reply(
            "🎉 Поздравляем с покупкой!\n"
            "После перепродажи нажмите кнопку <b>💰 Продал</b> на карточке товара, чтобы зафиксировать прибыль.",
            parse_mode="HTML"
        )
        
    elif action == "reply":
        def get_ad_reply():
            with db_session() as session:
                ad = AdRepository.get_by_id(session, ad_id)
                if ad:
                    return ad.title, ad.price
                return None
                
        ad_reply = await asyncio.to_thread(get_ad_reply)
        if not ad_reply:
            await callback.answer("❌ Объявление не найдено", show_alert=True)
            return
            
        title, price = ad_reply
        await callback.answer("💬 Шаблон сгенерирован")
        template = (
            f"📋 <b>Шаблон сообщения продавцу (нажмите, чтобы скопировать):</b>\n\n"
            f"<code>Доброго дня! Чи актуальне оголошення \"{title}\" за {format_price(price)}? "
            f"Все працює справно? Чи є дефекти або ремонти? Чи можлива OLX Доставка? Дякую!</code>"
        )
        await callback.message.reply(template, parse_mode="HTML")
        
    elif action == "send_olx":
        if not settings.olx_bearer_token:
            await callback.answer("❌ Прямая отправка не настроена! Укажите токен OLX_BEARER_TOKEN в .env", show_alert=True)
            return
            
        await callback.answer()
        builder = InlineKeyboardBuilder()
        builder.button(text="💬 Вопрос по товару", callback_data=f"deal:send_olx_tpl:{ad_id}")
        builder.button(text="📉 Предложить цену (Торг)", callback_data=f"deal:send_olx_offer:{ad_id}")
        builder.button(text="📦 Хочу купить (OLX Доставка)", callback_data=f"deal:send_olx_buy:{ad_id}")
        builder.button(text="✍️ Написать свой текст", callback_data=f"deal:send_olx_txt:{ad_id}")
        builder.button(text="❌ Отмена", callback_data=f"deal:send_olx_cancel:{ad_id}")
        builder.adjust(1)
        
        await callback.message.reply(
            "✉️ <b>Прямая отправка сообщения на OLX:</b>\n\n"
            "Выберите способ:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        
    elif action == "send_olx_cancel":
        await callback.answer("Отменено")
        await callback.message.delete()
        
    elif action == "send_olx_tpl":
        await callback.answer("Отправка шаблона...")
        def get_ad_tpl():
            with db_session() as session:
                ad = AdRepository.get_by_id(session, ad_id)
                if ad:
                    return ad.title, ad.price, ad.olx_id
                return None
                
        ad_tpl = await asyncio.to_thread(get_ad_tpl)
        if not ad_tpl:
            await callback.message.answer("❌ Объявление не найдено.")
            return
            
        title, price, olx_id = ad_tpl
        tpl_msg = (
            f"Доброго дня! Чи актуальне оголошення \"{title}\" за {format_price(price)}? "
            f"Все працює справно? Чи є дефекти або ремонти? Чи можлива OLX Доставка? Дякую!"
        )
        
        success, msg = await OLXChatService.send_message(olx_id, tpl_msg)
        if success:
            await callback.message.edit_text(f"✅ {msg}")
        else:
            await callback.message.edit_text(f"❌ {msg}")
            
    elif action == "send_olx_buy":
        await callback.answer("Отправка запроса...")
        def get_ad_buy():
            with db_session() as session:
                ad = AdRepository.get_by_id(session, ad_id)
                if ad:
                    return ad.title, ad.olx_id
                return None
                
        ad_buy = await asyncio.to_thread(get_ad_buy)
        if not ad_buy:
            await callback.message.answer("❌ Объявление не найдено.")
            return
            
        title, olx_id = ad_buy
        buy_msg = (
            f"Доброго дня! Чи актуальне оголошення \"{title}\"? "
            f"Чи можлива OLX Доставка? Готовий оформити прямо зараз. Дякую!"
        )
        
        success, msg = await OLXChatService.send_message(olx_id, buy_msg)
        if success:
            await callback.message.edit_text(f"✅ {msg}")
        else:
            await callback.message.edit_text(f"❌ {msg}")
            
    elif action == "send_olx_offer":
        await callback.answer()
        await state.update_data(ad_id=ad_id, choice_msg_id=callback.message.message_id)
        await state.set_state(OLXMessageState.waiting_for_offer_price)
        await callback.message.edit_text(
            "📉 <b>Предложить цену (Торг):</b>\n\n"
            "Введите цену в гривнах (только цифры), которую вы хотите предложить продавцу:",
            parse_mode="HTML"
        )
        
    elif action == "send_olx_txt":
        await callback.answer()
        await state.update_data(ad_id=ad_id, choice_msg_id=callback.message.message_id)
        await state.set_state(OLXMessageState.waiting_for_message)
        await callback.message.edit_text(
            "✍️ <b>Напишите текст сообщения:</b>\n\n"
            "Введите сообщение, которое бот отправит продавцу напрямую в чат OLX:",
            parse_mode="HTML"
        )
        
    elif action == "rescan":
        await callback.answer("🔄 Пересканирую...")
        status_msg = await callback.message.reply("⏳ Перепарсиваю объявление через Playwright...")

        try:
            from app.crawler.browser import OLXBrowser
            from app.crawler.parser import parse_ad
            from app.services.engine import load_watchlist

            def get_ad_rescan():
                with db_session() as session:
                    ad = AdRepository.get_by_id(session, ad_id)
                    if ad:
                        return ad.price, ad.url, ad.category, ad.watch_item_id
                    return None
                    
            ad_rescan = await asyncio.to_thread(get_ad_rescan)
            if not ad_rescan:
                await status_msg.edit_text("❌ Объявление не найдено в БД")
                return
                
            old_price, url, category, watch_item_id = ad_rescan

            watchlist = load_watchlist()
            watch_item = next((w for w in watchlist if w["id"] == watch_item_id), {})

            await status_msg.edit_text("🔄 Открываю страницу через Playwright...")
            browser = OLXBrowser(headless=True)
            await browser.start()
            try:
                fresh_data = await parse_ad(browser, url)
                if not fresh_data:
                    await status_msg.edit_text("❌ Не удалось перепарсить объявление")
                    return
            finally:
                await browser.close()

            new_price = fresh_data.get("price", 0)
            from app.scoring.ai_analyzer import analyze_listing_with_ai
            await status_msg.edit_text("🤖 AI переанализирует объявление...")
            analysis = await analyze_listing_with_ai(
                fresh_data.get("title", ""), fresh_data.get("description", ""), new_price
            )

            def save_rescan():
                with db_session() as session:
                    ad = AdRepository.get_by_id(session, ad_id)
                    if ad:
                        ad.title = fresh_data.get("title", ad.title)
                        ad.price = new_price
                        ad.description = fresh_data.get("description", ad.description)
                        ad.image_url = fresh_data.get("photos", [None])[0] or ad.image_url
                        ad.estimated_market_price = sum(watch_item.get("normal_price_range", [0, 0])) / 2
            
            await asyncio.to_thread(save_rescan)

            price_change = ""
            if old_price > 0 and new_price > 0:
                diff = old_price - new_price
                pct = (diff / old_price) * 100
                if diff > 0:
                    price_change = f"\n\n📉 <b>Цена изменилась:</b> {format_price(old_price)} → {format_price(new_price)} (<b>-{pct:.0f}%</b>)"
                    if pct >= 15:
                        price_change += "\n🔥 <b>Цена упала!</b> Самое время брать!"
                elif diff < 0:
                    price_change = f"\n\n📈 <b>Цена выросла:</b> {format_price(old_price)} → {format_price(new_price)} (<b>+{abs(pct):.0f}%</b>)"
                else:
                    price_change = "\n\n🔄 Цена не изменилась"

            defects = analysis.get("defects", [])
            defects_text = f"\n⚠️ <b>AI выявил дефекты:</b> {', '.join(defects)}" if defects else "\n✅ AI: дефектов не обнаружено"
            verdict = analysis.get("verdict", "")
            verdict_text = f"\n🤖 <b>Вердикт AI:</b> {verdict}" if verdict else ""

            report = (
                f"🔄 <b>Результат пересканирования</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🏷 {fresh_data.get('title', '')[:100]}\n"
                f"💰 {format_price(new_price)}\n"
                f"{price_change}"
                f"{defects_text}"
                f"{verdict_text}"
            )

            from app.bot.keyboards import get_rescan_keyboard
            await status_msg.edit_text(report, parse_mode="HTML", reply_markup=get_rescan_keyboard(ad_id, 0))

        except Exception as e:
            logger.error("Rescan error: {}", e)
            await status_msg.edit_text(f"❌ Ошибка пересканирования: {e}")

    elif action == "sold":
        await callback.answer()
        await state.update_data(ad_id=ad_id)
        await state.set_state(SellState.waiting_for_buy_price)
        await callback.message.reply(
            "💰 <b>Фиксация продажи товара</b>\n\n"
            "Шаг 1: Введите цену, за которую вы КУПИЛИ товар (только цифры, в грн):",
            parse_mode="HTML"
        )

# --- FSM Handlers ---

@router.message(SellState.waiting_for_buy_price)
async def process_buy_price(message: Message, state: FSMContext):
    if message.chat.id != settings.telegram_chat_id:
        return
        
    buy_price = clean_price(message.text)
    if buy_price <= 0:
        await message.answer("❌ Пожалуйста, введите корректное число больше нуля:")
        return
        
    await state.update_data(buy_price=buy_price)
    await state.set_state(SellState.waiting_for_sell_price)
    await message.answer(
        "Шаг 2: Введите цену, за которую вы ПРОДАЛИ товар (только цифры, в грн):"
    )

@router.message(SellState.waiting_for_sell_price)
async def process_sell_price(message: Message, state: FSMContext):
    if message.chat.id != settings.telegram_chat_id:
        return
        
    sell_price = clean_price(message.text)
    if sell_price <= 0:
        await message.answer("❌ Пожалуйста, введите корректное число больше нуля:")
        return
        
    data = await state.get_data()
    ad_id = data["ad_id"]
    buy_price = data["buy_price"]
    
    profit = sell_price - buy_price
    roi = (profit / buy_price) * 100.0 if buy_price > 0 else 0.0
    
    def save_sale():
        with db_session() as session:
            ad = AdRepository.get_by_id(session, ad_id)
            if ad:
                ad.status = "sold"
                category = ad.category
                watch_item_id = ad.watch_item_id
                
                record_outcome(session, ad_id, "sold", buy_price, sell_price)

                feedback = UserFeedback(
                    ad_id=ad_id,
                    action="sold",
                    buy_price=buy_price,
                    sell_price=sell_price,
                    profit=profit,
                    roi=roi
                )
                FeedbackRepository.add(session, feedback)

                CategoryStatsRepository.increment_stats(
                    session, category, sold=1, profit=profit
                )
                
                apply_feedback_learning(category, watch_item_id, "sold")
                return ad.title
            return None
            
    ad_title = await asyncio.to_thread(save_sale)
    if ad_title:
        logger.info("Flip recorded. Ad: {}. Profit: {}, ROI: {:.2f}%", ad_id, profit, roi)
        
        await message.answer(
            f"🎉 <b>Сделка зафиксирована!</b>\n\n"
            f"🏷 Товар: {ad_title}\n"
            f"📥 Цена покупки: {format_price(buy_price)}\n"
            f"📤 Цена продажи: {format_price(sell_price)}\n"
            f"💵 Чистая прибыль: <b>{format_price(profit)}</b>\n"
            f"📈 ROI: <b>{roi:.2f}%</b>",
            parse_mode="HTML"
        )
    else:
        await message.answer("❌ Ошибка: объявление не найдено в базе данных.")
            
    await state.clear()


@router.message(OLXMessageState.waiting_for_message)
async def process_olx_custom_message(message: Message, state: FSMContext):
    if message.chat.id != settings.telegram_chat_id:
        return
        
    text = message.text.strip()
    if not text:
        await message.answer("❌ Сообщение не может быть пустым. Напишите текст:")
        return
        
    data = await state.get_data()
    ad_id = data["ad_id"]
    choice_msg_id = data.get("choice_msg_id")
    
    def get_ad_olx_id():
        with db_session() as session:
            ad = AdRepository.get_by_id(session, ad_id)
            return ad.olx_id if ad else None
            
    olx_id = await asyncio.to_thread(get_ad_olx_id)
    if not olx_id:
        await message.answer("❌ Объявление не найдено в базе данных.")
        await state.clear()
        return
        
    status_msg = await message.answer("⏳ Отправка сообщения на OLX...")
    
    success, msg = await OLXChatService.send_message(olx_id, text)
    
    if success:
        await status_msg.edit_text(f"✅ {msg}")
        if choice_msg_id:
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=choice_msg_id)
            except Exception:
                pass
    else:
        await status_msg.edit_text(f"❌ {msg}")
        
    await state.clear()


@router.message(OLXMessageState.waiting_for_offer_price)
async def process_olx_offer_price(message: Message, state: FSMContext):
    if message.chat.id != settings.telegram_chat_id:
        return
        
    price_text = message.text.strip()
    price = clean_price(price_text)
    if price <= 0:
        await message.answer("❌ Пожалуйста, введите корректное число больше нуля:")
        return
        
    data = await state.get_data()
    ad_id = data["ad_id"]
    choice_msg_id = data.get("choice_msg_id")
    
    def get_ad_details():
        with db_session() as session:
            ad = AdRepository.get_by_id(session, ad_id)
            return (ad.olx_id, ad.title) if ad else (None, None)
            
    olx_id, title = await asyncio.to_thread(get_ad_details)
    if not olx_id:
        await message.answer("❌ Объявление не найдено в базе данных.")
        await state.clear()
        return
        
    status_msg = await message.answer("⏳ Отправка предложения на OLX...")
    
    offer_msg = (
        f"Доброго дня! Чи поступитеся в ціні до {format_price(price)}? "
        f"Якщо згодні, можу оформити OLX Доставку прямо зараз. Дякую!"
    )
    
    success, msg = await OLXChatService.send_message(olx_id, offer_msg)
    
    if success:
        await status_msg.edit_text(f"✅ {msg}")
        if choice_msg_id:
            try:
                await message.bot.delete_message(chat_id=message.chat.id, message_id=choice_msg_id)
            except Exception:
                pass
    else:
        await status_msg.edit_text(f"❌ {msg}")
        
    await state.clear()
