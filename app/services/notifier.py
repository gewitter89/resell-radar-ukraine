"""
Telegram notification system with AI deal badges and visual indicators.
"""
from aiogram import Bot
from app.storage.models import Ad
from app.utils.money import format_price
from app.utils.logger import logger
from app.bot.keyboards import get_deal_keyboard

_DEAL_BADGES = [
    (90, "🔥 МЕГА-СДЕЛКА", "🟢"),
    (85, "🔥 СУПЕР-СДЕЛКА", "🟢"),
    (80, "💎 ОТЛИЧНАЯ СДЕЛКА", "🟢"),
    (75, "✅ ВЫГОДНЫЙ ВАРИАНТ", "🟢"),
    (65, "🟡 СРЕДНИЙ ВАРИАНТ", "🟡"),
    (50, "🟠 ПОСРЕДСТВЕННО", "🟠"),
    (0, "🔴 НЕ РЕКОМЕНДУЕТСЯ", "🔴"),
]

_RISK_BADGES = [
    (60, "⛔️ ВЫСОКИЙ РИСК"),
    (40, "⚠️ СРЕДНИЙ РИСК"),
    (20, "⚜️ НИЗКИЙ РИСК"),
    (0, "✅ БЕЗОПАСНО"),
]

_PROFIT_BADGES = [
    (5000, "💰💰💰"),
    (3000, "💰💰"),
    (1500, "💰"),
    (0, ""),
]


def _get_badge(score: int, table: list) -> tuple:
    for threshold, badge, *rest in table:
        if score >= threshold:
            return (badge, *rest) if rest else (badge,)
    return (table[-1][0],)


def format_ad_notification(ad: Ad, watch_item: dict) -> str:
    normal_range = watch_item.get("normal_price_range", [0, 0])
    market_range_str = f"{format_price(normal_range[0])}–{format_price(normal_range[1])}"

    min_profit = max(0, normal_range[0] - ad.price)
    max_profit = max(0, normal_range[1] - ad.price)
    expected_profit_str = f"~{format_price(min_profit)}–{format_price(max_profit)}"

    deal_badge, deal_icon = _get_badge(ad.deal_score, _DEAL_BADGES)
    risk_badge = _get_badge(ad.risk_score, _RISK_BADGES)[0]
    profit_emoji = _get_badge(max_profit, _PROFIT_BADGES)[0]

    banner = f"{deal_icon} {deal_badge}"
    profit_pct = ((normal_range[0] - ad.price) / ad.price * 100) if ad.price > 0 else 0

    # ── AI анализ состояния / перепродажи ───────────────────────────
    ai_block = ""
    if ad.analysis_json:
        aj = ad.analysis_json
        ct_map = {
            "new": "🆕 Новый",
            "used_like_new": "📱 Б/у как новый",
            "used_good": "📱 Б/у хорошее",
            "used_defects": "🔧 Б/у с дефектами",
            "for_parts": "💀 На запчасти",
        }
        liq_map = {
            "instant": "⚡️ Мгновенно",
            "fast": "🚀 Быстро (1-3 дня)",
            "normal": "📦 Нормально (до 2 нед)",
            "slow": "🐢 Медленно (до мес)",
            "hard": "❌ Тяжело (мес+)",
        }
        urg_map = {
            "high": "🔥 Срочно!",
            "medium": "⏳ Средняя",
            "low": "🕐 Не срочно",
        }
        sat_map = {
            "low": "🟢 Низкая",
            "medium": "🟡 Средняя",
            "high": "🟠 Высокая",
            "very_high": "🔴 Очень высокая",
        }
        seller_map = {
            "low": "✅ Надёжный",
            "medium": "⚠️ С осторожностью",
            "high": "❌ Рисковый",
        }
        season_map = {
            "peak": "🌻 Пик сезона",
            "normal": "🍂 Нормально",
            "off_season": "❄️ Не сезон",
        }
        conf_map = {
            "high": "🤖 Уверен",
            "medium": "🤖 Средне",
            "low": "🤖 Предположение",
        }

        ct = ct_map.get(aj.get("condition_type", ""), "📱 Б/у")
        erp = aj.get("estimated_resell_price", 0)
        eprof = aj.get("expected_profit", 0)
        netp = aj.get("net_profit", eprof)
        bp = aj.get("bargain_price", 0)
        liq = liq_map.get(aj.get("liquidity", ""), "")
        urg = urg_map.get(aj.get("urgency", ""), "")
        sat = sat_map.get(aj.get("market_saturation", ""), "")
        seller = seller_map.get(aj.get("seller_risk", ""), "")
        seller_reason = aj.get("seller_risk_reason", "")
        season = season_map.get(aj.get("seasonality", ""), "")
        conf = conf_map.get(aj.get("confidence", ""), "")
        verdict = aj.get("verdict", "")

        lines = [f"📋 <b>AI аналитика:</b>"]
        lines.append(f"  {ct} · Оценка: {aj.get('condition_score', '?')}/100")
        if erp:
            margin = ((erp - ad.price) / ad.price * 100) if ad.price > 0 else 0
            lines.append(f"  💰 Перепродажа: ~{format_price(erp)}")
            lines.append(f"  📈 Валовая прибыль: <b>+{format_price(eprof)}</b> (<b>+{margin:.0f}%</b>)")
            if netp and abs(netp - eprof) > 100:
                lines.append(f"  🧾 Чистая прибыль: <b>{format_price(netp)}</b> (после комиссий)")
        if bp:
            save_pct = ((ad.price - bp) / ad.price * 100) if ad.price > 0 else 0
            lines.append(f"  💬 Торг: c <b>{format_price(bp)}</b> (−{save_pct:.0f}%)")
        if liq and urg:
            lines.append(f"  ⏱ {liq} · {urg}")
        if sat:
            lines.append(f"  📊 Конкуренция: {sat}")
        if season:
            lines.append(f"  📅 Сезонность: {season}")
        if seller:
            reason_text = f" — {seller_reason}" if seller_reason else ""
            lines.append(f"  👤 Продавец: {seller}{reason_text}")
        defects = aj.get("defects", [])
        if defects:
            lines.append(f"  ⚠️ {', '.join(defects[:3])}")
        if conf:
            lines.append(f"  {conf}")
        if verdict:
            lines.append(f"  💡 {verdict[:200]}")

        ai_block = "\n".join(lines)

    # ── Причины ─────────────────────────────────────────────────────
    reasons = []
    market_median = (normal_range[0] + normal_range[1]) / 2.0

    if ad.price <= watch_item.get("max_green_price", 0):
        reasons.append("🟢 Цена ниже зелёной границы (автопокупка)")
    if market_median > 0 and ad.price <= market_median * 0.7:
        reasons.append("🔥 Скидка >30% от рынка")
    elif market_median > 0 and ad.price <= market_median * 0.85:
        reasons.append("💰 Цена ниже рынка на 15%+")
    if ad.risk_score <= 20:
        reasons.append("✅ Минимальный риск")
    if ad.image_url:
        reasons.append("📸 Есть реальные фото")
    if profit_pct >= 40:
        reasons.append(f"📈 Маржа {profit_pct:.0f}% — супер-прибыль")
    elif profit_pct >= 25:
        reasons.append(f"📈 Маржа {profit_pct:.0f}% — отличная прибыль")
    if not reasons:
        reasons.append("💡 Приемлемое соотношение прибыли к риску")

    reasons_str = "\n".join(reasons)
    published_str = ad.published_at.strftime("%H:%M") if ad.published_at else "Только что"

    # ── Сборка сообщения ────────────────────────────────────────────
    parts = [
        f"{banner}\n",
        f"<b>{watch_item.get('name', ad.title)[:200]}</b>",
        "",
        f"💰 <b>Цена:</b> {format_price(ad.price)} {profit_emoji}",
        f"📊 <b>Рынок:</b> {market_range_str}",
        f"💵 <b>Потенциал:</b> {expected_profit_str} (<b>+{profit_pct:.0f}%</b>)",
        "",
        f"📍 {ad.location or 'Украина'} · 🕐 {published_str}",
    ]

    if ai_block:
        parts += ["", ai_block]

    parts += [
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"{deal_icon} Deal Score: {ad.deal_score}/100 · {deal_badge}",
        f"{risk_badge} Risk Score: {ad.risk_score}/100",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"<b>Почему стоит брать:</b>",
        reasons_str,
        "",
        f"🔗 <a href='{ad.url}'>Открыть на OLX</a>",
    ]

    return "\n".join(parts)


def format_super_deal(ad: Ad, watch_item: dict) -> str:
    """Формат для супер-сделок: максимально ярко, крупно, заметно."""
    normal_range = watch_item.get("normal_price_range", [0, 0])
    profit_pct = ((normal_range[0] - ad.price) / ad.price * 100) if ad.price > 0 else 0
    profit = normal_range[0] - ad.price

    return (
        f"🚨🚨 <b>СУПЕР-СДЕЛКА!</b> 🚨🚨\n\n"
        f"🔥🔥🔥 <b>{watch_item.get('name', ad.title)[:150]}</b> 🔥🔥🔥\n\n"
        f"💸 <b>Цена:</b> {format_price(ad.price)}\n"
        f"📊 <b>Рынок до:</b> {format_price(normal_range[1])}\n"
        f"💰 <b>Потенциальная прибыль:</b> {format_price(profit)} (<b>+{profit_pct:.0f}%</b>)\n"
        f"{'━'*25}\n"
        f"🟢 <b>Score:</b> {ad.deal_score}/100\n"
        f"✅ <b>Риск:</b> {ad.risk_score}/100\n"
        f"{'━'*25}\n\n"
        f"⏱ <b>Не упусти!</b> Такие предложения улетают за минуты.\n\n"
        f"🔗 <a href='{ad.url}'>Открыть на OLX</a>"
    )


async def send_ad_notification(bot: Bot, chat_id: int, ad: Ad, watch_item: dict) -> bool:
    text = format_ad_notification(ad, watch_item)
    kb = get_deal_keyboard(ad.id)

    # Super-deal threshold: маржа >40% И risk <25
    normal_range = watch_item.get("normal_price_range", [0, 0])
    is_super = (ad.price <= normal_range[0] * 0.6 and ad.risk_score <= 25 and ad.deal_score >= 85)

    if is_super:
        from app.services.learning import apply_feedback_learning
        apply_feedback_learning(ad.category, ad.watch_item_id, "super_deal")
        text = format_super_deal(ad, watch_item)

    try:
        if ad.image_url:
            await bot.send_photo(
                chat_id=chat_id,
                photo=ad.image_url,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        return True
    except Exception as e:
        logger.warning("Photo failed, retry as text: {}", e)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Exception as e2:
            logger.error("Notification failed: {}", e2)
            return False
