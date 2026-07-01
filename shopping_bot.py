"""
Shopping Bot — 24/7 long-running aiogram bot.
Commands: /start /price /promo /cart /add /remove /repeat /order /menu /history
Inline buttons on every product card.
SQLite for cart + price history + orders.
"""
import asyncio
import json
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Load .env
from dotenv import load_dotenv
ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import httpx

from auto_shopper import (
    zakaz_search_product, zakaz_top_promos,
    np_delivery_prices, smart_filter, format_report,
    load_config, KYIV_STORES, ZAKAZ_BASE, zakaz_get,
    run_cycle, send_telegram,
)
from delivery_kyiv import calculate_best_delivery, KYIV_STORE_DELIVERY

# ====================================================================
# CONFIG
# ====================================================================
CONFIG_PATH = Path(__file__).parent / "shopping_list.json"
DB_PATH = Path(__file__).parent / "shopping.db"
KYIV_TZ = timezone(timedelta(hours=3))
log = logging.getLogger("shopping_bot")

router = Router()


# ====================================================================
# DB
# ====================================================================
def db_init():
    with sqlite3.connect(DB_PATH) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product TEXT UNIQUE NOT NULL,
            qty REAL DEFAULT 1,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product TEXT NOT NULL,
            store TEXT,
            price REAL,
            url TEXT,
            checked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            items TEXT,
            total REAL,
            items_count INTEGER,
            created_at TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_latest
            ON prices(product, store, checked_at);
        """)


def cart_add(product: str, qty: float = 1.0):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            INSERT INTO cart (product, qty, added_at)
            VALUES (?, ?, ?)
            ON CONFLICT(product) DO UPDATE SET
                qty = qty + excluded.qty,
                added_at = excluded.added_at
        """, (product, qty, datetime.now(KYIV_TZ).isoformat()))


def cart_remove(product: str):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM cart WHERE product = ?", (product,))


def cart_list() -> list[tuple[str, float]]:
    with sqlite3.connect(DB_PATH) as c:
        return c.execute("SELECT product, qty FROM cart ORDER BY added_at").fetchall()


def cart_clear():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM cart")


def price_save(product: str, store: str, price: float, url: str):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            INSERT INTO prices (product, store, price, url, checked_at)
            VALUES (?, ?, ?, ?, ?)
        """, (product, store, price, url, datetime.now(KYIV_TZ).isoformat()))


def price_history(product: str, days: int = 7) -> list[tuple[str, float]]:
    """Returns [(date, price)] for product, last `days` days, best per day."""
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute("""
            SELECT date(checked_at) as d, MIN(price)
            FROM prices
            WHERE product = ? AND checked_at >= date('now', ?)
            GROUP BY d
            ORDER BY d
        """, (product, f"-{days} days")).fetchall()
    return rows


def order_save(items: list[dict], total: float):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            INSERT INTO orders (items, total, items_count, created_at)
            VALUES (?, ?, ?, ?)
        """, (json.dumps(items, ensure_ascii=False), total, len(items),
              datetime.now(KYIV_TZ).isoformat()))


def order_last() -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as c:
        row = c.execute("""
            SELECT items, total, items_count, created_at
            FROM orders ORDER BY id DESC LIMIT 1
        """).fetchone()
    if not row:
        return None
    items, total, count, created = row
    return {"items": json.loads(items), "total": total,
            "count": count, "created": created}


def alert_init():
    """Create price_alerts table if missing."""
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product TEXT NOT NULL,
                old_price REAL,
                new_price REAL,
                percent REAL,
                store TEXT,
                notified_at TEXT
            )
        """)


def alert_save(product: str, old_price: float, new_price: float, store: str):
    """Save price-drop alert."""
    percent = ((new_price - old_price) / old_price) * 100
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            INSERT INTO price_alerts (product, old_price, new_price, percent, store, notified_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (product, old_price, new_price, percent, store,
              datetime.now(KYIV_TZ).isoformat()))


def alert_recent(days: int = 7) -> list[dict]:
    """Return recent alerts."""
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute("""
            SELECT product, old_price, new_price, percent, store, notified_at
            FROM price_alerts
            WHERE notified_at >= datetime('now', ?)
            ORDER BY notified_at DESC
        """, (f"-{days} days",)).fetchall()
    return [{"product": r[0], "old": r[1], "new": r[2],
             "percent": r[3], "store": r[4], "time": r[5]} for r in rows]


async def price_drop_check(bot: Bot, chat_id: int):
    """Check cart products for price drops >20% from historical max."""
    items = cart_list()
    if not items:
        return

    log.info(f"🔍 PRICE CHECK: {len(items)} products")
    alerts = []

    for product, qty in items:
        hist = price_history(product, days=14)
        if len(hist) < 2:
            continue

        prices = [p for _, p in hist]
        max_price = max(prices)
        current_price = prices[-1]
        drop_percent = ((current_price - max_price) / max_price) * 100

        if drop_percent <= -20:
            store = "Zakaz.ua"
            alert_save(product, max_price, current_price, store)
            alerts.append({
                "product": product,
                "old": max_price,
                "new": current_price,
                "drop": drop_percent,
                "store": store,
            })
            log.info(f"📉 PRICE DROP: {product} {max_price:.0f} ₴ → {current_price:.0f} ₴ ({drop_percent:.1f}%)")

    if alerts:
        text = "🔔 <b>ЦЕНЫ УПАЛИ!</b>\n\n"
        for a in alerts:
            text += f"📉 <b>{a['product']}</b>\n"
            text += f"   Было: <s>{a['old']:.0f} ₴</s>\n"
            text += f"   Стало: <b>{a['new']:.0f} ₴</b> ({a['drop']:+.1f}%)\n"
            text += f"   📅 Магазин: {a['store']}\n\n"

        text += "💡 Пора заказывать пока цена низкая!"

        try:
            await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.error(f"❌ ALERT send failed: {e}")


async def weekly_report(bot: Bot, chat_id: int):
    """Weekly price history report for cart items."""
    items = cart_list()
    if not items:
        await bot.send_message(chat_id,
                               "📊 Корзина пуста. Добавь товары через /add.")
        return

    text = "📊 <b>ЕЖЕНЕДЕЛЬНЫЙ ОТЧЕТ О ЦЕНАХ</b>\n\n"
    text += f"📅 Период: последние 14 дней\n\n"

    for product, qty in items[:10]:
        hist = price_history(product, days=14)
        if not hist:
            continue

        prices = [p for _, p in hist]
        min_p, max_p, avg_p = min(prices), max(prices), sum(prices) / len(prices)
        current = prices[-1]
        change = ((current - min_p) / min_p) * 100 if min_p > 0 else 0

        trend = "📉" if change <= -10 else "📈" if change >= 10 else "➖"
        change_str = f"{change:+.1f}%" if change != 0 else "без изменений"

        text += f"<b>{product}</b>\n"
        text += f"  {trend} Сейчас: <b>{current:.0f} ₴</b> ({change_str})\n"
        text += f"  Min: {min_p:.0f} ₴ | Max: {max_p:.0f} ₴ | Avg: {avg_p:.0f} ₴\n"

        if len(hist) >= 3:
            sparkline = " → ".join([f"{p:.0f}" for p in prices[-5:]])
            text += f"  📈 Тренд: {sparkline}\n"
        text += "\n"

    text += "<i>Обновления каждые 4 часа. /history <product> для деталей.</i>"

    try:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.error(f"❌ Weekly report failed: {e}")


# ====================================================================
# FSM
# ====================================================================
class SearchStates(StatesGroup):
    waiting_product = State()


# ====================================================================
# HELPERS
# ====================================================================
def product_kb(product: str, chain: str, price: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ В корзину", callback_data=f"add:{product}"),
            InlineKeyboardButton(text="🔔 Цена", callback_data=f"price:{product}"),
        ],
        [
            InlineKeyboardButton(text="📜 История", callback_data=f"hist:{product}"),
            InlineKeyboardButton(text="🔄 Сравнить", callback_data=f"cmp:{product}"),
        ],
    ])


def cart_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Оформить", callback_data="order"),
            InlineKeyboardButton(text="🗑 Очистить", callback_data="cart_clear"),
        ],
        [
            InlineKeyboardButton(text="🔁 Повторить заказ", callback_data="repeat"),
        ],
    ])


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔥 Промо", callback_data="menu:promo"),
            InlineKeyboardButton(text="🛒 Корзина", callback_data="menu:cart"),
        ],
        [
            InlineKeyboardButton(text="📋 Меню дня", callback_data="menu:menu"),
            InlineKeyboardButton(text="📈 История", callback_data="menu:hist"),
        ],
        [
            InlineKeyboardButton(text="🔁 Повтор", callback_data="menu:repeat"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help"),
        ],
    ])


async def fetch_live_price(query: str) -> Optional[dict]:
    """Fetch best live price from Zakaz.ua now."""
    deals = await zakaz_search_product(query, limit=5)
    if not deals:
        return None
    best = deals[0]
    # Save to history
    price_save(query, best["store"], best["price"], best.get("url", ""))
    for d in deals[1:4]:
        price_save(query, d["store"], d["price"], d.get("url", ""))
    return {"deals": deals, "best": best}


# ====================================================================
# COMMANDS
# ====================================================================
@router.message(CommandStart())
async def cmd_start(msg: Message):
    await msg.answer(
        "🛒 <b>Shopping Bot</b> — персональный помощник по магазинам.\n\n"
        "Ищу лучшие цены, веду корзину, считаю доставку, делаю меню.\n\n"
        "<b>Команды:</b>\n"
        "  /price <i>продукт</i> — цены сейчас\n"
        "  /promo — топ скидок дня\n"
        "  /add <i>продукт</i> — в корзину\n"
        "  /remove <i>продукт</i> — убрать из корзины\n"
        "  /cart — показать корзину\n"
        "  /delivery — сравнить варианты доставки\n"
        "  /order — оформить заказ\n"
        "  /repeat — повторить прошлый заказ\n"
        "  /alerts — последние уведомления по ценам\n"
        "  /history <i>продукт</i> — цены за 2 недели\n"
        "  /menu — эконом-меню дня (Groq AI)\n"
        "  /clear — очистить корзину\n"
        "  /list — твой список покупок\n"
        "  /help — подробная справка",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "📚 <b>СПРАВКА</b>\n\n"
        "<b>🔍 Цены и поиск:</b>\n"
        "  • <code>/price молоко 1л</code> — цены сейчас во всех магазинах\n"
        "  • <code>/promo</code> — топ-10 скидок дня (до -56%)\n"
        "  • Поддерживает RU→UA перевод: «куриные бёдра» → «стегно куряче»\n\n"
        "<b>🛒 Корзина:</b>\n"
        "  • <code>/add 2 молоко 1л</code> — добавить 2×молоко\n"
        "  • <code>/cart</code> — показать корзину с живыми ценами\n"
        "  • <code>/delivery</code> — сравнить доставку по магазинам\n"
        "  • <code>/order</code> — оформить с расчётом суммы\n"
        "  • <code>/repeat</code> — повторить прошлый заказ\n\n"
        "<b>📊 Аналитика:</b>\n"
        "  • <code>/history рис 1кг</code> — цены за 14 дней (min/max/trend)\n"
        "  • <code>/alerts</code> — уведомления о падении цен ≥20%\n"
        "  • Автоматические алерты каждые 4 часа для товаров в корзине\n"
        "  • Еженедельный отчёт каждый понедельник 10:00\n\n"
        "<b>🍽 Меню:</b>\n"
        "  • <code>/menu 500</code> — эконом-меню на 500₴ в день\n"
        "  • Groq AI (Llama 3.3 70B) + реальные цены Zakaz.ua\n\n"
        "<b>🚚 Доставка:</b>\n"
        "  • Zakaz.ua: 59 ₴ (бесплатно от 1200 ₴)\n"
        "  • Novus: 59 ₴ (бесплатно от 800 ₴)\n"
        "  • Silpo: 79 ₴ (бесплатно от 1000 ₴)\n"
        "  • ATB: только самовывоз\n\n"
        "<b>📦 Stores:</b> Zakaz.ua → Metro/Auchan/Novus, Silpo, Varus, Maudau, ATB",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("price"))
async def cmd_price(msg: Message, state: FSMContext):
    query = (msg.text or "").replace("/price", "", 1).strip()
    if not query:
        await state.set_state(SearchStates.waiting_product)
        await msg.answer("🔍 Напиши продукт, например: <code>молоко 1л</code>",
                         parse_mode=ParseMode.HTML)
        return
    await send_price(msg, query)


async def send_price(msg: Message, query: str):
    wait_msg = await msg.answer(f"⏳ Ищу «<b>{query}</b>»...")
    result = await fetch_live_price(query)
    if not result:
        await wait_msg.edit_text(f"❌ «{query}» не найден")
        return

    best = result["best"]
    deals = result["deals"]

    lines = [f"<b>🔍 {query}</b>\n"]
    lines.append(f"💰 <b>{best['price']:.0f} ₴</b> —{best['store']}  "
                 f"<a href='{best.get('url', '')}'>🛒 купить</a>")

    others = [d for d in deals[1:4] if d["store"] != best["store"]]
    for d in others[:3]:
        lines.append(f"  • {d['store']}: {d['price']:.0f} ₴  <a href='{d.get('url', '')}'>→</a>")

    # Price trend vs last week
    hist = price_history(query, days=7)
    if len(hist) >= 2:
        prev = hist[0][1]
        curr = best["price"]
        delta = curr - prev
        pct = (delta / prev * 100) if prev > 0 else 0
        emoji = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
        lines.append(f"\n{emoji} За неделю: {delta:+.0f} ₴ ({pct:+.1f}%)")

    lines.append(f"\n<i>Добавить в корзину: /add {query}</i>")
    await wait_msg.edit_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=product_kb(query, best["chain"], best["price"]),
        disable_web_page_preview=True,
    )


@router.message(SearchStates.waiting_product)
async def got_product(msg: Message, state: FSMContext):
    await state.clear()
    await send_price(msg, msg.text.strip())


@router.message(Command("promo"))
async def cmd_promo(msg: Message):
    wait_msg = await msg.answer("⏳ Собираю скидки...")
    promos = await zakaz_top_promos("all", min_pct=25, limit=15)
    if not promos:
        await wait_msg.edit_text("Пока нет скидок")
        return

    lines = ["🔥 <b>СКИДКИ ДНЯ В КИЕВЕ</b>\n"]
    for d in promos[:12]:
        due = f" · до {d['due_date']}" if d.get("due_date") else ""
        lines.append(
            f"<b>−{d['discount_pct']}%</b>  {d['price']:.0f} ₴ "
            f"<s>{d['old_price']:.0f}</s>  "
            f"<a href='{d['url']}'>{d['title'][:42]}</a>\n"
            f"   🏪 {d['store']}{due}"
        )
    await wait_msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML,
                              disable_web_page_preview=True)


@router.message(Command("add"))
async def cmd_add(msg: Message):
    product = (msg.text or "").replace("/add", "", 1).strip()
    if not product:
        await msg.answer("Используй: <code>/add молоко 1л</code>",
                         parse_mode=ParseMode.HTML)
        return
    # Split "qty product" if starts with number
    qty = 1.0
    parts = product.split(maxsplit=1)
    if len(parts) == 2:
        try:
            qty = float(parts[0])
            product = parts[1]
        except ValueError:
            pass
    cart_add(product, qty)
    count = len(cart_list())
    await msg.answer(
        f"✅ Добавлено в корзину: <b>{product}</b> (×{qty})\n"
        f"🛒 Всего в корзине: {count}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔍 Цена", callback_data=f"price:{product}"),
                InlineKeyboardButton(text="🛒 Корзина", callback_data="menu:cart"),
            ]
        ]),
    )


@router.message(Command("remove"))
async def cmd_remove(msg: Message):
    product = (msg.text or "").replace("/remove", "", 1).strip()
    if not product:
        await msg.answer("Используй: <code>/remove молоко 1л</code>",
                         parse_mode=ParseMode.HTML)
        return
    cart_remove(product)
    await msg.answer(f"🗑 Убрано: <b>{product}</b>", parse_mode=ParseMode.HTML)


@router.message(Command("cart"))
async def cmd_cart(msg: Message):
    items = cart_list()
    if not items:
        await msg.answer("🛒 Корзина пуста\n\nДобавь: <code>/add молоко 1л</code>",
                         parse_mode=ParseMode.HTML)
        return
    await show_cart(msg, items)


async def show_cart(msg: Message, items: list[tuple[str, float]]):
    lines = ["🛒 <b>ТВОЯ КОРЗИНА</b>\n"]
    total = 0.0
    cart_items = []
    stores_used = set()

    for product, qty in items:
        result = await fetch_live_price(product)
        if not result:
            lines.append(f"  ❌ {product} — не найден")
            continue
        best = result["best"]
        sub = best["price"] * qty
        total += sub
        stores_used.add(best["store"])
        cart_items.append({"product": product, "qty": qty,
                           "price": best["price"], "store": best["store"],
                           "url": best.get("url", "")})
        lines.append(
            f"  • <b>{product}</b> × {qty} = <b>{sub:.0f} ₴</b> "
            f"({best['store']}) <a href='{best.get('url', '')}'>→</a>"
        )

    lines.append(f"\n{'━' * 15}")
    lines.append(f"💰 <b>Сумма товаров:</b> {total:.0f} ₴")

    if stores_used:
        main_store = next(iter(stores_used))
        plan = calculate_best_delivery(main_store, total, weight_kg=3.0)
        store = KYIV_STORE_DELIVERY.get(main_store)

        if store and store.has_courier:
            if plan.is_free_delivery:
                lines.append(f"🚚 <b>Доставка:</b> <b>БЕСПЛАТНО</b> (от {store.free_from} ₴)")
            else:
                needed = store.free_from - total
                lines.append(
                    f"🚚 <b>Доставка:</b> {plan.store_delivery:.0f} ₴ "
                    f"(бесплатно от {store.free_from} ₴, осталось +{needed:.0f} ₴)"
                )
        elif store and store.has_pickup:
            lines.append(f"🏪 <b>Самовывоз:</b> бесплатно (доставки нет)")

        lines.append(f"{'━' * 15}")
        if plan.is_free_delivery or (store and not store.has_courier):
            lines.append(f"📦 <b>ИТОГО:</b> <b>{total:.0f} ₴</b>")
        else:
            lines.append(
                f"📦 <b>ИТОГО + доставка:</b> <b>{total + plan.store_delivery:.0f} ₴</b>"
            )
        lines.append(f"💡 {plan.recommendation}")
    else:
        lines.append(f"🚚 <b>НП Відділення:</b> ~70₴ | <b>Кур'єр:</b> ~95₴")
        lines.append(f"{'━' * 15}")
        lines.append(f"📦 <b>ИТОГО + доставка:</b> {total + 70:.0f} ₴ / {total + 95:.0f} ₴")

    if cart_items:
        order_save(cart_items, total)

    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML,
                     reply_markup=cart_kb(), disable_web_page_preview=True)


@router.message(Command("clear"))
async def cmd_clear(msg: Message):
    cart_clear()
    await msg.answer("🗑 Корзина очищена")


@router.message(Command("list"))
async def cmd_list(msg: Message):
    """Show saved shopping list from config."""
    cfg = load_config()
    cats = cfg.get("categories", {})
    if not cats:
        await msg.answer("Список пуст")
        return
    lines = ["📋 <b>ТВОЙ СПИСОК ПОКУПОК</b>\n"]
    for cat, items in cats.items():
        lines.append(f"\n<b>{cat}</b>")
        for item in items:
            lines.append(f"  • {item}")
    lines.append("\n<i>Добавить в корзину: /add продукт</i>")
    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(Command("repeat"))
async def cmd_repeat(msg: Message):
    last = order_last()
    if not last:
        await msg.answer("Предыдущих заказов нет")
        return
    cart_clear()
    for item in last["items"]:
        cart_add(item["product"], item["qty"])
    await msg.answer(
        f"🔁 Повторяю прошлый заказ ({last['count']} товаров, "
        f"{last['total']:.0f} ₴):\n"
        + "\n".join(f"  • {i['product']} × {i['qty']}" for i in last["items"])
        + "\n\nПосмотреть: /cart",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("history"))
async def cmd_history(msg: Message):
    query = (msg.text or "").replace("/history", "", 1).strip()
    if not query:
        await msg.answer("Используй: <code>/history молоко 1л</code>",
                         parse_mode=ParseMode.HTML)
        return
    hist = price_history(query, days=14)
    if not hist:
        await msg.answer(f"Нет данных по «{query}» за 14 дней")
        return
    lines = [f"📈 <b>История цен: {query}</b>\n"]
    prices = [p for _, p in hist]
    for date, price in hist[-10:]:
        lines.append(f"  {date}: <b>{price:.0f} ₴</b>")
    if len(prices) >= 2:
        min_p = min(prices)
        max_p = max(prices)
        delta = prices[-1] - prices[0]
        pct = (delta / prices[0] * 100) if prices[0] > 0 else 0
        lines.append(f"\n📊 Мин: {min_p:.0f} ₴  ·  Макс: {max_p:.0f} ₴")
        emoji = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
        lines.append(f"{emoji} За период: {delta:+.0f} ₴ ({pct:+.1f}%)")
    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(Command("alerts"))
async def cmd_alerts(msg: Message):
    """Show recent price-drop alerts."""
    alerts = alert_recent(days=7)
    if not alerts:
        await msg.answer(
            "🔔 Нет уведомлений за последние 7 дней.\n\n"
            "Добавь товары в корзину через /add — получишь алерты когда цены упадут на ≥20%.",
            parse_mode=ParseMode.HTML)
        return

    text = f"🔔 <b>ПОСЛЕДНИЕ ПАДЕНИЯ ЦЕН</b> (7 дней)\n\n"
    for a in alerts[:10]:
        text += f"📉 <b>{a['product']}</b>\n"
        text += f"   <s>{a['old']:.0f} ₴</s> → <b>{a['new']:.0f} ₴</b> ({a['percent']:+.1f}%)\n"
        text += f"   📅 {a['time'][:16]} · {a['store']}\n\n"

    text += f"<i>Всего: {len(alerts)} уведомлений</i>"
    await msg.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("delivery"))
async def cmd_delivery(msg: Message):
    """Compare delivery options for all stores."""
    items = cart_list()
    if not items:
        await msg.answer("🛒 Корзина пуста — нечего доставлять\n\nДобавь: <code>/add молоко 1л</code>",
                         parse_mode=ParseMode.HTML)
        return

    total = 0.0
    for product, qty in items:
        result = await fetch_live_price(product)
        if result:
            total += result["best"]["price"] * qty

    text = "🚚 <b>ВАРИАНТЫ ДОСТАВКИ</b>\n\n"
    text += f"💰 Сумма заказа: <b>{total:.0f} ₴</b>\n\n"

    for store_name, store in KYIV_STORE_DELIVERY.items():
        plan = calculate_best_delivery(store_name, total, weight_kg=3.0)
        free_tag = "✅ <b>БЕСПЛАТНО</b>" if plan.is_free_delivery else f"{plan.store_delivery:.0f} ₴"

        if not store.has_courier:
            text += f"🏪 <b>{store_name}</b> — {free_tag}\n"
            text += f"    {store.notes}\n"
        else:
            text += f"🚚 <b>{store_name}</b> — {free_tag}\n"
            if not plan.is_free_delivery:
                needed = store.free_from - total
                text += f"    Бесплатно от {store.free_from} ₴ (+{needed:.0f} ₴)\n"
        text += f"    💵 Итого: <b>{plan.total:.0f} ₴</b>\n\n"

    text += "<i>Nova Poshta — отдельно для междугородней доставки.</i>"
    await msg.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("menu"))
async def cmd_menu(msg: Message):
    """Economy menu for today — Groq AI powered. Usage: /menu [budget]"""
    from ai_menu import build_daily_menu
    # Optional budget argument
    budget = 300.0
    parts = (msg.text or "").split()
    if len(parts) >= 2:
        try:
            budget = float(parts[1])
        except ValueError:
            pass
    await build_daily_menu(msg, budget=budget)


@router.message(Command("order"))
async def cmd_order(msg: Message):
    """Show cart with final prices."""
    items = cart_list()
    if not items:
        await msg.answer("Корзина пуста. Добавь через /add")
        return
    await show_cart(msg, items)


# ====================================================================
# CALLBACK (inline buttons)
# ====================================================================
@router.callback_query(F.data.startswith("add:"))
async def cb_add(call: CallbackQuery):
    product = call.data[4:]
    cart_add(product, 1.0)
    await call.answer(f"✅ Добавлено в корзину: {product}")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.callback_query(F.data.startswith("remove:"))
async def cb_remove(call: CallbackQuery):
    product = call.data[7:]
    cart_remove(product)
    await call.answer(f"🗑 Убрано: {product}")


@router.callback_query(F.data.startswith("price:"))
async def cb_price(call: CallbackQuery):
    product = call.data[6:]
    result = await fetch_live_price(product)
    if not result:
        await call.answer(f"❌ {product} не найден")
        return
    best = result["best"]
    await call.answer(
        f"💰 {product}: {best['price']:.0f}₴ в {best['store']}",
        show_alert=True, cache_time=60,
    )


@router.callback_query(F.data.startswith("hist:"))
async def cb_hist(call: CallbackQuery):
    product = call.data[5:]
    hist = price_history(product, days=14)
    if not hist:
        await call.answer(f"Нет данных по {product}", show_alert=True)
        return
    text = f"📈 {product}:\n" + "\n".join(
        f"  {d}: {p:.0f}₴" for d, p in hist[-7:]
    )
    if len(hist) >= 2:
        delta = hist[-1][1] - hist[0][1]
        text += f"\n\nΔ = {delta:+.0f}₴"
    await call.answer(text, show_alert=True, cache_time=30)


@router.callback_query(F.data.startswith("cmp:"))
async def cb_compare(call: CallbackQuery):
    product = call.data[4:]
    result = await fetch_live_price(product)
    if not result:
        await call.answer(f"❌ {product} не найден")
        return
    deals = result["deals"][:5]
    text = f"🔄 {product} — сравнение:\n\n"
    for d in deals:
        text += f"  • {d['store']}: <b>{d['price']:.0f} ₴</b>\n"
    await call.message.answer(text, parse_mode=ParseMode.HTML)
    await call.answer()


@router.callback_query(F.data == "cart_clear")
async def cb_cart_clear(call: CallbackQuery):
    cart_clear()
    await call.answer("🗑 Корзина очищена")
    try:
        await call.message.edit_text("🛒 Корзина пуста")
    except Exception:
        pass


@router.callback_query(F.data == "order")
async def cb_order(call: CallbackQuery):
    """Finalize order."""
    items = cart_list()
    if not items:
        await call.answer("Корзина пуста")
        return
    # Build order text
    lines = ["✅ <b>ЗАКАЗ ОФОРМЛЕН</b>\n"]
    total = 0
    for product, qty in items:
        result = await fetch_live_price(product)
        if result:
            best = result["best"]
            sub = best["price"] * qty
            total += sub
            lines.append(f"  • {product} × {qty} = <b>{sub:.0f}₴</b> "
                         f"({best['store']}) <a href='{best.get('url','')}'>→</a>")
    lines.append(f"\n💰 <b>Сумма:</b> {total:.0f} ₴")
    lines.append(f"🚚 <b>С доставкой:</b> {total + 70:.0f} ₴")

    # Build a big Zakaz.ua link with cart items (just search links)
    if items:
        searches = " ".join(q for q, _ in items[:5])
        lines.append(f"\n🔗 <b>Искать на Zakaz.ua:</b> "
                     f"<a href='https://zakaz.ua/search/?q={searches}'>все товары</a>")

    await call.message.answer("\n".join(lines), parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
    await call.answer("✅ Заказ сформирован")
    cart_clear()


@router.callback_query(F.data == "repeat")
async def cb_repeat(call: CallbackQuery):
    last = order_last()
    if not last:
        await call.answer("Нет предыдущих заказов")
        return
    cart_clear()
    for item in last["items"]:
        cart_add(item["product"], item["qty"])
    await call.answer(f"🔁 Добавлено {len(last['items'])} товаров")
    items = cart_list()
    await show_cart(call.message, items)


@router.callback_query(F.data == "menu:cart")
async def cb_menu_cart(call: CallbackQuery):
    items = cart_list()
    if not items:
        await call.message.answer("🛒 Корзина пуста\n/add молоко")
        await call.answer()
        return
    await show_cart(call.message, items)
    await call.answer()


@router.callback_query(F.data == "menu:promo")
async def cb_menu_promo(call: CallbackQuery):
    promos = await zakaz_top_promos("all", min_pct=25, limit=12)
    if not promos:
        await call.message.answer("Пока нет скидок")
        await call.answer()
        return
    lines = ["🔥 <b>СКИДКИ ДНЯ</b>\n"]
    for d in promos:
        lines.append(f"<b>−{d['discount_pct']}%</b> {d['price']:.0f}₴ "
                     f"<s>{d['old_price']:.0f}</s> "
                     f"<a href='{d['url']}'>{d['title'][:38]}</a> "
                     f"🏪 {d['store']}")
    await call.message.answer("\n".join(lines), parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data == "menu:repeat")
async def cb_menu_repeat(call: CallbackQuery):
    last = order_last()
    if not last:
        await call.answer("Нет предыдущих заказов")
        return
    cart_clear()
    for item in last["items"]:
        cart_add(item["product"], item["qty"])
    await call.answer(f"🔁 Добавлено {len(last['items'])} товаров")
    items = cart_list()
    await show_cart(call.message, items)


@router.callback_query(F.data == "menu:menu")
async def cb_menu_menu(call: CallbackQuery):
    from ai_menu import build_daily_menu
    await build_daily_menu(call.message)
    await call.answer()


@router.callback_query(F.data == "menu_add_all")
async def cb_menu_add_all(call: CallbackQuery):
    """Add menu core products to cart."""
    core = ["молоко 1л", "яйца 10шт", "хлеб белый", "куриное филе 1кг",
            "рис 1кг", "помидоры 1кг"]
    for p in core:
        cart_add(p, 1.0)
    await call.answer(f"✅ Добавлено {len(core)} продуктов в корзину")


@router.callback_query(F.data == "menu_500")
async def cb_menu_500(call: CallbackQuery):
    from ai_menu import build_daily_menu
    await build_daily_menu(call.message, budget=500.0)
    await call.answer()


@router.callback_query(F.data == "menu_800")
async def cb_menu_800(call: CallbackQuery):
    from ai_menu import build_daily_menu
    await build_daily_menu(call.message, budget=800.0)
    await call.answer()


@router.callback_query(F.data == "menu:hist")
async def cb_menu_hist(call: CallbackQuery):
    await call.message.answer(
        "📈 Используй: <code>/history молоко 1л</code>",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(call: CallbackQuery):
    await call.message.answer(
        "🛒 <b>Shopping Bot — помощь</b>\n\n"
        "/price продукт — цены сейчас\n"
        "/promo — скидки дня\n"
        "/add продукт — в корзину\n"
        "/cart — показать корзину + оформить\n"
        "/repeat — повторить прошлый\n"
        "/history продукт — цены за неделю\n"
        "/menu — эконом-меню AI\n"
        "/list — мой список покупок\n"
        "/clear — очистить корзину",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


# ====================================================================
# CRON (3x daily reports merged into the same bot)
# ====================================================================
async def cron_worker(bot: Bot):
    """Background task: runs report at 9/13/18 every day."""
    cfg = load_config()
    schedule = cfg.get("schedule_hours", [9, 13, 18])
    chat_id = cfg.get("telegram_chat_id", 0)
    log.info(f"⏰ CRON: will run at {schedule}:00")

    last_hour = None
    last_price_check = None
    last_weekly = None
    while True:
        now = datetime.now(KYIV_TZ)
        h = now.hour
        m = now.minute

        if h in schedule and h != last_hour and m < 2:
            last_hour = h
            log.info(f"🚀 CRON: running schedule {h}:00")
            try:
                report = await run_cycle()
                if report:
                    await send_telegram(report, cfg.get("telegram_bot_token", ""),
                                         chat_id)
                    log.info("📨 Report sent")
            except Exception as e:
                log.error(f"❌ CRON failed: {e}")
        elif h not in schedule:
            last_hour = None

        # Price drop check every 4 hours
        if last_price_check is None or (now - last_price_check).total_seconds() > 4 * 3600:
            try:
                await price_drop_check(bot, chat_id)
                last_price_check = now
            except Exception as e:
                log.error(f"❌ Price check failed: {e}")

        # Weekly report on Monday at 10:00
        if now.weekday() == 0 and h == 10 and m < 2 and last_weekly is None:
            try:
                await weekly_report(bot, chat_id)
                last_weekly = now
                log.info("📊 Weekly report sent")
            except Exception as e:
                log.error(f"❌ Weekly report failed: {e}")
        elif now.weekday() != 0:
            last_weekly = None

        await asyncio.sleep(60)


# ====================================================================
# MAIN
# ====================================================================
async def main():
    cfg = load_config()
    token = cfg.get("telegram_bot_token", "")
    if not token:
        log.error("No telegram_bot_token in shopping_list.json")
        return

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")

    db_init()
    alert_init()

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Start cron as background task
    cron_task = asyncio.create_task(cron_worker(bot))

    log.info("🤖 Shopping Bot запущен (24/7 + cron)")
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        cron_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
