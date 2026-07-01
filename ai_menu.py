"""
AI Economy Menu — Groq-powered daily meal plan under 300₴.
Uses Zakaz.ua real prices to build realistic menu.
"""
import os
import httpx
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timezone, timedelta
from pathlib import Path

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from auto_shopper import zakaz_search_product, load_config

KYIV_TZ = timezone(timedelta(hours=3))
DB_PATH = Path(__file__).parent / "shopping.db"


async def fetch_groq(prompt: str) -> str:
    """Call Groq API (OpenAI-compatible). Free tier."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    # Fallback: try shopping_list.json
    if not api_key:
        cfg = load_config()
        api_key = cfg.get("groq_api_key", "")
    if not api_key:
        return "⚠️ GROQ_API_KEY не задан. Добавь в .env или shopping_list.json"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system",
             "content": "Ты шеф-повар и нутрициолог. Отвечай кратко, по делу, по-русски."
                        " Используй конкретные цены и продукты из входных данных."
                        " Структура ответа: Завтрак/Обед/Ужин с ценой и КБЖУ."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 800,
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers, json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ Ошибка Groq: {e}"


async def build_daily_menu(msg: Message, budget: float = 300.0):
    """Build daily economy menu with real prices."""
    wait = await msg.answer(f"🍽 Собираю меню на {budget:.0f}₴...")

    # Fetch real prices for core products
    core_products = [
        "молоко 1л", "яйца 10шт", "хлеб белый", "макароны 500г",
        "куриное филе 1кг", "pomидоры 1кг", "рис 1кг",
    ]
    price_data = []

    for product in core_products:
        deals = await zakaz_search_product(product, limit=3)
        if deals:
            best = deals[0]
            price_data.append(f"{product}: {best['price']:.0f}₴ ({best['store']})")

    today = datetime.now(KYIV_TZ).strftime("%Y-%m-%d")

    prompt = f"""Сегодня {today}. Составь эконом-меню на день для 1 человека за {budget:.0f} грн.

Реальные цены в магазинах Киева:
{chr(10).join(price_data) if price_data else "нет данных"}

Структура ответа:
1. 🌅 Завтрак — название блюда, ингредиенты, цена, ккал
2. ☀️ Обед
3. 🌙 Ужин
4. 💰 ИТОГО: сумма ₴ и ккал/день
5. 🛒 Список покупок: что купить сегодня

Без воды. Кратко. С ценами. Блюда простые украинские.
"""

    menu_text = await fetch_groq(prompt)

    text = f"🍽 <b>ЭКОНОМ-МЕНЮ {today}</b>\n" \
           f"💰 Бюджет: <b>{budget:.0f} ₴</b>\n\n" \
           f"{menu_text}\n\n" \
           f"<i>Изменить бюджет: /menu 500</i>"

    # Add inline buttons for quick add
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛒 Добавить всё в корзину",
                                  callback_data="menu_add_all"),
        ],
        [
            InlineKeyboardButton(text="💰 Меню за 500₴", callback_data="menu_500"),
            InlineKeyboardButton(text="💰 Меню за 800₴", callback_data="menu_800"),
        ],
    ])

    await wait.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb,
                          disable_web_page_preview=True)
