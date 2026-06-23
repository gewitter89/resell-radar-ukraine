"""
Smart Budget — итоговая аналитика + order links + price-drop alerts.

Что даёт:
  1. Итоговая стоимость корзины в каждом магазине с доставкой
  2. Прямая ссылка "заказать" (Zakaz.ua, Silpo, MAUDAU)
  3. Price-drop alert — если цена упала ниже исторической, мгновенный алерт
"""

import asyncio
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from grocery_scanner import ShoppingResult, find_cheapest
from delivery_kyiv import (
    calculate_best_delivery, KYIV_STORE_DELIVERY, get_store_delivery_info,
)
from price_tracker import tracker, PriceTracker
from np_api import get_delivery_to_my_address, format_my_delivery


@dataclass
class StoreTotal:
    store: str
    products_total: float
    delivery_cost: float
    total: float
    product_count: int
    is_free_delivery: bool = False
    order_url: str = ""
    missing_products: list[str] = field(default_factory=list)


@dataclass
class BudgetReport:
    date: str
    products_found: int
    products_total: int
    store_totals: list[StoreTotal]
    best_store: StoreTotal
    total_savings: float
    alerts: list[dict]  # price-drop alerts
    delivery_to_me: dict | None = None  # реальный расчёт НП


# === ORDER LINKS ===

ORDER_URLS = {
    "Zakaz.ua": "https://zakaz.ua/uk/",
    "Silpo": "https://silpo.ua/checkout",
    "MAUDAU": "https://maudau.com.ua/checkout",
    "Novus": "https://novus.com.ua/checkout",
    "Metro": "https://metro.ua/checkout",
    "Auchan": "https://auchan.ua/basket",
    "Varus": "https://varus.ua/checkout",
}


# === БЮДЖЕТНЫЙ ОТЧЁТ ===

async def calculate_budget(
    category_results: dict[str, list[ShoppingResult]],
    weight_kg: float = 5.0,
    city: str = "Киев",
    floor: int = 1,
    use_my_address: bool = True,
) -> BudgetReport:
    """Полный бюджетный анализ: все магазины + доставка + order links + алерты."""

    # Расчёт доставки на мой адрес (реальный API НП)
    delivery_to_me = None
    if use_my_address:
        try:
            # Считаем общую сумму корзины для НП
            all_products_flat = []
            for results in category_results.values():
                all_products_flat.extend(results)
            cart_total = sum(
                r.best_offer.price for r in all_products_flat
                if r.best_offer and r.best_offer.price > 0
            )
            delivery_to_me = await get_delivery_to_my_address(
                cart_value=cart_total or 500,
                weight_kg=weight_kg,
            )
        except Exception:
            pass

    # Собрать все продукты
    all_products: list[ShoppingResult] = []
    for results in category_results.values():
        all_products.extend(results)

    products_with_prices = [p for p in all_products if p.offers]
    total_products = len(all_products)

    # Группировка по магазинам
    store_products: dict[str, list[ShoppingResult]] = {}
    for result in products_with_prices:
        if result.best_offer:
            store = result.best_offer.store
            if store not in store_products:
                store_products[store] = []
            store_products[store].append(result)

    # Расчёт по каждому магазину
    store_totals: list[StoreTotal] = []
    alerts: list[dict] = []

    for store, products in store_products.items():
        products_total = sum(p.best_offer.price for p in products)
        info = get_store_delivery_info(store)

        if info and info.has_courier:
            plan = calculate_best_delivery(store, products_total, weight_kg, floor)
            delivery_cost = plan.store_delivery
            total = plan.total
            is_free = plan.is_free_delivery
        else:
            delivery_cost = 0
            total = products_total
            is_free = False

        # Missing products (those not in this store)
        found_names = {p.product for p in products}
        missing = [p.product for p in products_with_prices if p.product not in found_names]

        store_totals.append(StoreTotal(
            store=store,
            products_total=products_total,
            delivery_cost=delivery_cost,
            total=total,
            product_count=len(products),
            is_free_delivery=is_free,
            order_url=ORDER_URLS.get(store, ""),
            missing_products=missing,
        ))

    # Сортировка: дешёвые первыми
    store_totals.sort(key=lambda s: s.total)

    best = store_totals[0] if store_totals else None
    worst = store_totals[-1] if len(store_totals) > 1 else None
    total_savings = (worst.total - best.total) if best and worst else 0

    # === PRICE-DROP ALERTS ===
    for result in products_with_prices:
        for offer in result.offers[:3]:
            trend = tracker.get_trend(result.product, offer.store)

            if trend["deal_quality"] == "best":
                alerts.append({
                    "type": "best_price",
                    "product": result.product,
                    "store": offer.store,
                    "price": offer.price,
                    "message": f"🔥 {result.product}: {offer.store} — {offer.price:.0f} ₴ (почти исторический минимум!)",
                })
            elif trend["direction"] == "down" and trend["change_pct"] <= -5:
                alerts.append({
                    "type": "price_drop",
                    "product": result.product,
                    "store": offer.store,
                    "price": offer.price,
                    "change_pct": trend["change_pct"],
                    "message": (
                        f"📉 {result.product}: {offer.store} — {offer.price:.0f} ₴ "
                        f"(упала на {abs(trend['change_pct']):.0f}% за неделю!)"
                    ),
                })

        # Сохраняем в историю
        for offer in result.offers:
            tracker.record(
                result.product,
                offer.store,
                offer.price,
                offer.old_price,
                offer.discount_pct,
            )

    return BudgetReport(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        products_found=len(products_with_prices),
        products_total=total_products,
        store_totals=store_totals,
        best_store=best,
        total_savings=total_savings,
        alerts=alerts,
        delivery_to_me=delivery_to_me,
    )


# === ФОРМАТ ДЛЯ TELEGRAM ===

def format_budget_report(report: BudgetReport) -> str:
    """Красивый отчёт для Telegram."""

    lines = ["💰 <b>БЮДЖЕТНЫЙ РАСЧЁТ</b>"]
    lines.append("─" * 28)

    # По магазинам
    for st in report.store_totals[:6]:
        emoji_map = {
            "ATB": "🟡", "Silpo": "🟢", "Auchan": "🔴",
            "Metro": "🔵", "Novus": "🟣", "Varus": "🟠",
            "MAUDAU": "🟤", "Zakaz.ua": "📦",
        }
        emoji = emoji_map.get(st.store, "⚪")

        free_badge = " ✅ БЕСПЛАТНО" if st.is_free_delivery else ""
        delivery_str = f" + {st.delivery_cost:.0f} дост." if st.delivery_cost > 0 else ""

        lines.append(
            f"{emoji} <b>{st.store}</b>: "
            f"{st.products_total:.0f}{delivery_str} = "
            f"<b>{st.total:.0f} ₴</b>{free_badge} "
            f"({st.product_count} поз.)"
        )

        if st.missing_products:
            lines.append(f"   ❌ Нет: {', '.join(st.missing_products[:3])}")

        if st.order_url:
            lines.append(f"   🔗 <a href='{st.order_url}'>Заказать</a>")

    lines.append("─" * 28)

    if report.best_store:
        lines.append(
            f"🏆 <b>Лучший вариант:</b> {report.best_store.store} — "
            f"{report.best_store.total:.0f} ₴"
        )
        lines.append(f"💸 <b>Экономия:</b> {report.total_savings:.0f} ₴")

    # Алерты
    if report.alerts:
        lines.append("")
        lines.append("🚨 <b>АЛЕРТЫ ЦЕН:</b>")
        for alert in report.alerts[:5]:
            lines.append(f"  {alert['message']}")

    lines.append("")
    lines.append(f"📦 Найдено: {report.products_found}/{report.products_total}")
    lines.append(f"🕐 {report.date}")

    # Доставка на мой адрес
    if report.delivery_to_me:
        lines.append("")
        lines.append(format_my_delivery(report.delivery_to_me))

    return "\n".join(lines)


# === МГНОВЕННЫЕ АЛЕРТЫ ===

async def check_price_drops(product: str, threshold_pct: float = 10.0) -> list[str]:
    """
    Проверить упала ли цена на продукт более чем на threshold_pct%.
    Использовать для мгновенных алертов мимо основного расписания.
    """
    result = await find_cheapest(product)
    if not result.offers:
        return []

    alerts = []
    for offer in result.offers[:3]:
        trend = tracker.get_trend(product, offer.store)
        drop = abs(trend.get("change_pct", 0))

        if trend["direction"] == "down" and drop >= threshold_pct:
            alerts.append(
                f"📉 <b>ЦЕНА УПАЛА!</b>\n"
                f"{product}: {offer.store} — <b>{offer.price:.0f} ₴</b>\n"
                f"Снижение: <b>-{drop:.0f}%</b> за неделю\n"
                f"Мин. за 30 дней: {trend['min_30d']:.0f} ₴"
            )

    return alerts
