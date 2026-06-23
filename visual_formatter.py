"""
Visual Telegram Formatter — красивая подача результатов шоппера.

Формат сообщения:
  ┌─────────────────────────────────┐
  │  🛒 УТРЕННИЙ ОБЗОР ЦЕН          │
  │  📅 Пн, 23 Июня · 09:00         │
  │  📍 Киев                         │
  ├─────────────────────────────────┤
  │  🥛 МОЛОЧКА / ЯЙЦА              │
  │  ┌──────────────────────────┐   │
  │  │ 🥛 Молоко 1л             │   │
  │  │ 1. ATB        32.90 ₴   │   │
  │  │ 2. Silpo      34.50 ₴   │   │
  │  │ 3. Auchan     36.00 ₴   │   │
  │  │ 💰 ATB дешевле на 3.10 ₴│   │
  │  └──────────────────────────┘   │
  │  ...                             │
  ├─────────────────────────────────┤
  │  🏆 ЛУЧШИЕ ПРЕДЛОЖЕНИЯ ДНЯ:     │
  │  🥇 Молоко 1л — ATB (32.90)     │
  │  🥈 Яйца 10шт — MAUDAU (58.00)  │
  │  🥉 Хлеб — ATB (15.90)          │
  ├─────────────────────────────────┤
  │  📊 ИТОГО:                       │
  │  Корзина: 1,234 ₴               │
  │  ATB (самовывоз): 1,050 ₴       │
  │  Silpo + доставка: 1,289 ₴      │
  │  💸 Экономия дня: 239 ₴         │
  └─────────────────────────────────┘
"""

import json
from datetime import datetime
from typing import Optional
from pathlib import Path

from grocery_scanner import ShoppingResult, StoreOffer


# === Эмодзи магазинов ===
STORE_EMOJI = {
    "ATB": "🟡",
    "Silpo": "🟢",
    "Auchan": "🔴",
    "Metro": "🔵",
    "Novus": "🟣",
    "Varus": "🟠",
    "MAUDAU": "🟤",
    "Zakaz.ua": "📦",
}

STORE_ORDER = ["ATB", "Silpo", "Auchan", "Metro", "Novus", "Varus", "MAUDAU", "Zakaz.ua"]

# === Эмодзи категорий ===
CATEGORY_EMOJI = {
    "🥛 Молочка / Яйца": "🥛",
    "🍞 Хлеб / Выпечка": "🍞",
    "🥩 Мясо / Рыба": "🥩",
    "🥬 Овощи / Фрукты": "🥬",
    "🍝 Бакалея": "🍝",
    "🧃 Напитки": "🧃",
    "🧴 Бытовая химия": "🧴",
}


def _time_of_day(hour: int) -> str:
    if hour < 12:
        return "УТРЕННИЙ"
    elif hour < 17:
        return "ДНЕВНОЙ"
    else:
        return "ВЕЧЕРНИЙ"


def _day_name() -> str:
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    months = ["Янв", "Фев", "Мар", "Апр", "Мая", "Июн",
              "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
    now = datetime.now()
    return f"{days[now.weekday()]}, {now.day} {months[now.month - 1]}"


def _price_bar(price: float, max_price: float, width: int = 8) -> str:
    """Визуальная полоска цены: ████░░░░"""
    if max_price <= 0:
        return "█" * width
    ratio = 1.0 - (price / max_price)
    filled = int(ratio * width)
    empty = width - filled
    if filled == 0 and ratio > 0:
        filled = 1
        empty = width - 1
    return "█" * filled + "░" * empty


# === ОСНОВНОЙ ФОРМАТТЕР ===

def format_header(city: str = "Киев") -> str:
    now = datetime.now()
    hour = now.hour
    tod = _time_of_day(hour)
    day = _day_name()

    return (
        f"🛒 <b>{tod} ОБЗОР ЦЕН</b>\n"
        f"📅 {day} · {now.strftime('%H:%M')}\n"
        f"📍 {city}\n"
        f"{'─' * 28}"
    )


def format_product_card(result: ShoppingResult, rank: int = 0) -> str:
    """Карточка продукта — ТОЛЬКО самое дешёвое предложение + кликабельная ссылка."""
    if not result.offers:
        return f"❌ <b>{result.product}</b> — не найдено"

    best = result.offers[0]  # самое дешёвое
    emoji = STORE_EMOJI.get(best.store, "⚪")

    # Скидка
    discount = ""
    if best.discount_pct > 0:
        discount = f" <b>-{best.discount_pct}%</b>"

    # Старая цена
    old_price_str = ""
    if best.old_price > 0:
        old_price_str = f" <s>{best.old_price:.0f} ₴</s>"

    # Ссылка
    name_display = best.product
    if best.url:
        name_display = f"<a href='{best.url}'>{best.product}</a>"

    lines = [
        f"<b>{name_display}</b>",
        f"  {emoji} <b>{best.store}</b> — <b>{best.price:.2f} ₴</b>{old_price_str}{discount}",
    ]

    # Если есть другие магазины — показать их цены мелко
    other_stores = [o for o in result.offers[1:4] if o.store != best.store]
    if other_stores:
        others = []
        for o in other_stores:
            o_emoji = STORE_EMOJI.get(o.store, "⚪")
            delta = f" (+{o.price - best.price:.0f})" if o.price > best.price else ""
            others.append(f"{o_emoji} {o.store}: {o.price:.0f} ₴{delta}")
        lines.append("  " + " · ".join(others))

    if result.savings > 0 and result.savings < result.offers[-1].price * 0.5:
        lines.append(f"  💰 Экономия: <b>{result.savings:.2f} ₴</b>")

    return "\n".join(lines)


def format_category_section(
    category_name: str,
    results: list[ShoppingResult]
) -> str:
    """Секция категории с продуктами."""
    if not results:
        return ""

    lines = []
    # Category header
    emoji = CATEGORY_EMOJI.get(category_name, "📦")
    lines.append(f"\n{emoji} <b>{category_name.upper()}</b>")
    lines.append("─" * 28)

    for result in results:
        if result.offers:
            lines.append(format_product_card(result))
            lines.append("")

    return "\n".join(lines)


def format_top3_deals(all_results: dict[str, list[ShoppingResult]]) -> str:
    """Топ-3 лучшие сделки дня (максимальная экономия)."""
    deals = []
    for cat_results in all_results.values():
        for result in cat_results:
            if result.offers and result.savings > 0:
                deals.append({
                    "product": result.product,
                    "store": result.min_store,
                    "price": result.min_price,
                    "savings": result.savings,
                    "savings_pct": (
                        (result.savings / result.offers[-1].price * 100)
                        if result.offers[-1].price > 0 else 0
                    ),
                })

    deals.sort(key=lambda d: d["savings_pct"], reverse=True)
    top3 = deals[:3]

    lines = ["\n🏆 <b>ЛУЧШИЕ ПРЕДЛОЖЕНИЯ ДНЯ:</b>"]
    medals = ["🥇", "🥈", "🥉"]
    for i, deal in enumerate(top3):
        emoji = STORE_EMOJI.get(deal["store"], "⚪")
        lines.append(
            f"  {medals[i]} {emoji} {deal['product']}: "
            f"<b>{deal['price']:.0f} ₴</b> "
            f"(экономия {deal['savings']:.0f} ₴ / {deal['savings_pct']:.0f}%)"
        )

    return "\n".join(lines)


def format_summary(
    all_results: dict[str, list[ShoppingResult]],
    city: str = "Киев",
) -> str:
    """Итоговая сводка с суммами по магазинам."""

    # Собрать все продукты
    all_products: list[ShoppingResult] = []
    for results in all_results.values():
        all_products.extend(results)

    # Посчитать по магазинам
    store_totals: dict[str, float] = {}
    store_counts: dict[str, int] = {}
    for result in all_products:
        if result.best_offer:
            store = result.best_offer.store
            store_totals[store] = store_totals.get(store, 0) + result.best_offer.price
            store_counts[store] = store_counts.get(store, 0) + 1

    if not store_totals:
        return ""

    cheapest_store = min(store_totals, key=store_totals.get)
    most_expensive_store = max(store_totals, key=store_totals.get)
    total_savings = store_totals[most_expensive_store] - store_totals[cheapest_store]
    total_products = sum(1 for r in all_products if r.offers)

    lines = ["\n📊 <b>ИТОГО ПО КОРЗИНЕ</b>"]
    lines.append("─" * 28)

    # По магазинам (сортируем от дешёвого к дорогому)
    for store, total in sorted(store_totals.items(), key=lambda x: x[1]):
        emoji = STORE_EMOJI.get(store, "⚪")
        count = store_counts.get(store, 0)

        # Доставка для этого магазина
        from delivery_kyiv import KYIV_STORE_DELIVERY, calculate_best_delivery
        info = KYIV_STORE_DELIVERY.get(store)
        if info and info.has_courier:
            plan = calculate_best_delivery(store, total, 5.0, 1)
            delivery_str = f" +{plan.store_delivery:.0f} дост. = {plan.total:.0f}"
            free_mark = " ✅ БЕСПЛАТНО" if plan.is_free_delivery else ""
        else:
            delivery_str = " (самовывоз)"
            free_mark = ""

        lines.append(
            f"  {emoji} <b>{store}</b>: {total:.0f} ₴"
            f"{delivery_str}{free_mark} ({count} поз.)"
        )

    lines.append("─" * 28)
    lines.append(
        f"💰 <b>Лучшая цена:</b> {cheapest_store} — {store_totals[cheapest_store]:.0f} ₴"
    )
    lines.append(
        f"⚠️ <b>Самая дорогая:</b> {most_expensive_store} — {store_totals[most_expensive_store]:.0f} ₴"
    )
    lines.append(
        f"💸 <b>Экономия при выборе лучшего:</b> {total_savings:.0f} ₴"
    )
    lines.append(f"📦 Всего позиций: {total_products}")

    return "\n".join(lines)


def format_delivery_options() -> str:
    """Блок с вариантами доставки НП."""
    from delivery_kyiv import _fallback_np_options
    options = _fallback_np_options(5.0, 1)

    lines = ["\n🚚 <b>ДОСТАВКА НОВОЙ ПОЧТОЙ</b>"]
    lines.append("─" * 28)
    for opt in options:
        lines.append(f"  {opt.name}: <b>{opt.cost:.0f} ₴</b>")

    return "\n".join(lines)


# === ГЛАВНЫЙ СБОРЩИК ОТЧЁТА ===

def build_full_report(
    category_results: dict[str, list[ShoppingResult]],
    city: str = "Киев",
) -> str:
    """Собирает полный отчёт для отправки в Telegram."""

    now = datetime.now()
    hour = now.hour

    sections = []

    # 1. Хедер
    sections.append(format_header(city))

    # 2. По категориям
    for category_name, results in category_results.items():
        section = format_category_section(category_name, results)
        if section.strip():
            sections.append(section)

    # 3. Топ-3 дня
    sections.append(format_top3_deals(category_results))

    # 4. Итого
    sections.append(format_summary(category_results, city))

    # 5. Доставка
    sections.append(format_delivery_options())

    # 6. Футер
    sections.append(
        f"\n{'─' * 28}\n"
        f"🤖 Следующий обзор: "
        f"{_next_run_time(hour)}\n"
        f"<i>Personal Shopper by Resell Radar</i>"
    )

    report = "\n".join(sections)

    # Telegram limit: 4096 chars
    if len(report) > 4000:
        # Split into parts
        return report[:4000] + "\n\n⚠️ Сообщение обрезано (лимит Telegram)"

    return report


def _next_run_time(current_hour: int) -> str:
    schedule = [9, 13, 18]
    for h in schedule:
        if h > current_hour:
            return f"{h}:00"
    return "09:00 (завтра)"
