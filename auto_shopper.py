"""
Unified Auto Shopper v2 — Zakaz.ua API + Hotline + НП доставка + 3x авто.

Что объединено:
  - Zakaz.ua REST API (реальные скидки Metro/Auchan/Novus — без скрейпинга!)
  - Hotline.ua (поиск любого товара по всей Украине)
  - Nova Poshta доставка на твой адрес (вул. Б. Антоненка-Давидовича, 1)
  - 3x/день авто-раннер (9:00, 13:00, 18:00)
  - Формат: 1 сообщение = всё сразу
"""

import asyncio
import json
import sys
import re
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import httpx

SCRIPT_DIR = Path(__file__).parent
LOCK_FILE = SCRIPT_DIR / "shopper.lock"
KYIV_TZ = timezone(timedelta(hours=3))
SCHEDULE_HOURS = [9, 13, 18]


def acquire_lock():
    """Prevent multiple instances from running."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            os.kill(pid, 0)
            print(f"Another instance running (PID {pid}). Exiting.")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            pass
    LOCK_FILE.write_text(str(os.getpid()))


def release_lock():
    LOCK_FILE.unlink(missing_ok=True)

# ====================================================================
# ZAKAZ.UA API (REAL REST — быстрее Playwright в 10 раз)
# ====================================================================

ZAKAZ_BASE = "https://stores-api.zakaz.ua"
ZAKAZ_HEADERS = {
    "User-Agent": "Mozilla/5.0 Chrome/125.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "uk",
}

FOOD_CATS = [
    "dairy-and-eggs", "fruits-and-vegetables", "meat-fish-poultry",
    "snacks-and-sweets", "packets-cereals", "drinks", "bakery",
    "tins-jars-cooking", "frozen",
]
HYGIENE_CATS = ["personal-hygiene", "household-chemicals", "household-and-cleaning", "babies"]
ALL_CATS = FOOD_CATS + HYGIENE_CATS

KYIV_STORES = {"novus": "482010105", "auchan": "48246401", "metro": "48215610"}


async def zakaz_get(client, url, chain, max_retries=3):
    """GET with exponential backoff retry."""
    backoff = 1.0
    for attempt in range(max_retries):
        try:
            r = await client.get(url, headers={**ZAKAZ_HEADERS, "x-chain": chain}, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", backoff * 2))
                await asyncio.sleep(min(wait, 10))
                continue
            if r.status_code >= 500:
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            return None
        except (httpx.TimeoutException, httpx.ConnectError):
            await asyncio.sleep(backoff)
            backoff *= 2
        except Exception:
            return None
    return None


async def zakaz_fetch_deals(
    chain: str, store_id: str, store_name: str,
    categories: list[str] | None = None,
    max_pages: int = 2, min_pct: int = 0,
) -> list[dict]:
    """Забирает скидки из одного магазина через Zakaz.ua API."""
    categories = categories or ALL_CATS
    deals = []
    async with httpx.AsyncClient() as client:
        for cid in categories:
            for page in range(1, max_pages + 1):
                url = f"{ZAKAZ_BASE}/stores/{store_id}/categories/{cid}/products/?page={page}"
                data = await zakaz_get(client, url, chain)
                if not data or not data.get("results"):
                    break
                for p in data["results"]:
                    d = p.get("discount") or {}
                    if not (d.get("status") and d.get("value")):
                        continue
                    pct = int(d["value"])
                    if pct < min_pct:
                        continue
                    deals.append({
                        "store": store_name,
                        "chain": chain,
                        "title": p.get("title", "").strip(),
                        "price": round(p.get("price", 0) / 100, 2),
                        "old_price": round((d.get("old_price") or 0) / 100, 2),
                        "discount_pct": pct,
                        "url": p.get("web_url", ""),
                        "due_date": d.get("due_date"),
                        "category": cid,
                    })
    return deals


import httpx
from datetime import datetime, timedelta
import re


# ====================================================================
# УМНЫЙ ФИЛЬТР (алгоритмический, без AI API)
# ====================================================================

def extract_weight(text: str) -> tuple[float, str] | None:
    """Извлекает вес/объем из строки. Возвращает (value_in_grams, unit)."""
    text = text.lower().replace(",", ".").replace(" ", "")
    patterns = [
        (r'(\d+\.?\d*)\s*(кг|kg)', lambda m: (float(m.group(1)) * 1000, 'g')),
        (r'(\d+\.?\d*)\s*(г|g|gr)\b', lambda m: (float(m.group(1)), 'g')),
        (r'(\d+\.?\d*)\s*(л|l|ltr)\b', lambda m: (float(m.group(1)) * 1000, 'ml')),
        (r'(\d+\.?\d*)\s*(мл|ml)\b', lambda m: (float(m.group(1)), 'ml')),
        (r'(\d+\.?\d*)\s*(шт|pc)', lambda m: (float(m.group(1)), 'pcs')),
        (r'(\d+\.?\d*)\s*(уп|pack)', lambda m: (float(m.group(1)), 'pcs')),
    ]
    for pattern, converter in patterns:
        match = re.search(pattern, text)
        if match:
            return converter(match)
    return None


def smart_filter(query: str, deals: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Фильтрует мусор из поиска.
    Возвращает (отфильтрованные результаты, причины отсева).
    """
    if not deals:
        return [], [f"'{query}': поиск пустой"]

    query_lower = query.lower()
    target_weight = extract_weight(query)
    filtered = []
    rejected = []

    # Ключевые слова для проверки соответствия
    query_keywords = set(re.findall(r'[а-яё]+', query_lower))

    # Blacklist: слова-маркеры мусора
    blacklist_map = {
        'індейк': ['корм', 'korm', 'pate', 'паштет'],
        'індич': ['корм', 'korm', 'pate', 'паштет', 'volohyi', 'вологий'],
        'куряч': ['корм', 'korm', 'pate', 'паштет'],
        'батон': ['батончик', 'snack', 'снек', 'шоколад'],
        'хліб': ['хлібці', 'сухарі', 'хруст', 'crisp'],
        'сир': ['плавлен', 'spread', 'spred'],
        'молоко': ['йогурт', 'кефір', 'ряжан'],
        'банани': ['сухофрукт', 'сушений', 'сушен', 'dried', 'чіпси', 'sukhofrukti'],
        'бананы': ['сухофрукт', 'сушенный', 'dried', 'чіпси'],
        'масло': ['печиво', 'суміш', 'маргарин'],
    }

    for deal in deals:
        title_lower = deal.get('title', '').lower()
        reason = None

        # 1. Проверяем что ключевые слова запроса есть в title
        title_words = set(re.findall(r'[а-яё]+', title_lower))
        overlap = query_keywords & title_words
        if not overlap and len(query_keywords) > 0:
            reason = f"нет ключевых слов ({query_keywords})"

        # 2. Проверяем по blacklist
        if not reason:
            for qword, bad_words in blacklist_map.items():
                if qword in query_lower:
                    for bad in bad_words:
                        if bad in title_lower:
                            reason = f"blacklist: '{bad}' не подходит для '{qword}'"
                            break
                    if reason:
                        break

        # 3. Проверяем вес
        if not reason and target_weight:
            deal_weight = extract_weight(deal.get('title', ''))
            if deal_weight:
                target_val, target_unit = target_weight
                deal_val, deal_unit = deal_weight
                # Допускаем отклонение ±50%
                if deal_val < target_val * 0.5:
                    reason = f"вес {deal_val} < {target_val}*0.5"
                elif deal_val > target_val * 3.0:
                    reason = f"вес {deal_val} > {target_val}*3"

        # 4. Sanity check: цена за "1кг картошки" не должна быть 339₴
        if not reason:
            price = deal.get('price', 0)
            if target_weight and target_weight[1] in ('g', 'ml'):
                target_val = target_weight[0]
                deal_w = extract_weight(deal.get('title', ''))
                if deal_w and deal_w[0] > 0:
                    price_per_kg = price / deal_w[0] * 1000
                    # Если цена за кг > 500₴ для базовых продуктов (картошка, лук, хлеб) — подозрительно
                    if any(w in query_lower for w in ['картоф', 'лук', 'хлеб', 'морков', 'свекл']):
                        if price_per_kg > 300:
                            reason = f"price/kg={price_per_kg:.0f}₴ слишком высокая"

        if reason:
            rejected.append(f"'{deal.get('title')[:40]}' — {reason}")
        else:
            filtered.append(deal)

    return filtered, rejected


QUERY_SYNONYMS = {
    "филе индейки": ["філе індички", "індичка філе", "індичка"],
    "батон": ["батон нарізний", "батон білий"],
    "хлеб белый": ["хліб білий", "хліб пшеничний нарізний"],
    "хлеб черный": ["хліб житній", "хліб чорний", "бородинський хліб"],
    "картофель 2кг": ["картопля 2кг", "картопля"],
    "лук 1кг": ["цибуля ріпчаста", "цибуля"],
    "помидоры 1кг": ["томати 1кг", "помідори"],
    "огурцы 1кг": ["огірки", "огірок"],
    "бананы 1кг": ["банани"],
    "куриное филе 1кг": ["куряче філе"],
    "куриные бедра": ["стегно куряче", "курячі стегна"],
    "сосиски молочные": ["сосиски молочні"],
    "молоко 1л": ["молоко"],
    "сыр твердый 200г": ["сир твердий", "сир"],
    "фарш свиной 500г": ["фарш свинячий", "свинячий фарш"],
}


async def zakaz_search_product(query: str, min_pct: int = 0, limit: int = 15) -> list[dict]:

    """Поиск конкретного продукта через Zakaz.ua API."""
    deals = []
    async with httpx.AsyncClient() as client:
        for chain, sid in KYIV_STORES.items():
            for page in range(1, 3):
                url = f"{ZAKAZ_BASE}/stores/{sid}/products/search/?q={query}&page={page}"
                data = await zakaz_get(client, url, chain)
                if not data or not data.get("results"):
                    break
                for p in data["results"]:
                    deals.append({
                        "store": chain.capitalize(),
                        "chain": chain,
                        "title": p.get("title", "").strip(),
                        "price": round(p.get("price", 0) / 100, 2),
                        "discount_pct": 0,
                        "url": p.get("web_url", ""),
                        "category": "search",
                    })

    seen = {}
    for d in deals:
        key = (d["title"].lower(), d["chain"])
        if key not in seen or d["price"] < seen[key]["price"]:
            seen[key] = d

    raw_results = sorted(seen.values(), key=lambda x: x["price"])[:limit]

    # Применяем умный фильтр
    filtered, rejected = smart_filter(query, raw_results)
    if rejected:
        print(f"🗑️ {query}: {len(rejected)} отсеяно ({', '.join(rejected[:2])})")

    # Если фильтр дал хоть что-то — возвращаем отфильтрованное
    if filtered:
        return filtered

    # Если пусто — пробуем синонимы (RU → UA)
    if query in QUERY_SYNONYMS:
        for synonym in QUERY_SYNONYMS[query]:
            print(f"🔄 {query} → synonym: {synonym}")
            syn_deals = []
            async with httpx.AsyncClient() as client:
                for chain, sid in KYIV_STORES.items():
                    url = f"{ZAKAZ_BASE}/stores/{sid}/products/search/?q={synonym}"
                    data = await zakaz_get(client, url, chain)
                    if data and data.get("results"):
                        for p in data["results"]:
                            syn_deals.append({
                                "store": chain.capitalize(),
                                "chain": chain,
                                "title": p.get("title", "").strip(),
                                "price": round(p.get("price", 0) / 100, 2),
                                "discount_pct": 0,
                                "url": p.get("web_url", ""),
                                "category": "search",
                            })
            # Фильтруем синоним-результаты (используем UA query!)
            syn_filtered, _ = smart_filter(synonym, syn_deals)
            if syn_filtered:
                print(f"✅ {query} → {synonym}: {len(syn_filtered)} найдено")
                return sorted(syn_filtered, key=lambda x: x["price"])[:limit]

    # Fallback: возвращаем сырые данные только если все выглядят нормально

    # (т.е. в title есть хоть одно слово из запроса)
    safe_raw = [d for d in raw_results[:3]
                if any(w in d.get("title", "").lower() for w in re.findall(r'[а-яё]+', query.lower()) if len(w) > 3)]

    if safe_raw:
        print(f"⚠️ {query}: фильтр пустой, возвращаю {len(safe_raw)} похожих")
        return safe_raw

    # Иначе — пусто, будет ❌ в отчете
    print(f"❌ {query}: ничего релевантного")
    return []


async def zakaz_top_promos(group: str = "all", min_pct: int = 30, limit: int = 20) -> list[dict]:
    """Топ скидок по Киеву."""
    cats = {"food": FOOD_CATS, "hygiene": HYGIENE_CATS}.get(group, ALL_CATS)
    all_deals = []
    for chain, sid in KYIV_STORES.items():
        try:
            all_deals += await zakaz_fetch_deals(chain, sid, chain.capitalize(), cats, min_pct=min_pct)
        except Exception:
            pass

    seen = {}
    for d in all_deals:
        key = (d["title"].lower(), d["chain"])
        if key not in seen or d["discount_pct"] > seen[key]["discount_pct"]:
            seen[key] = d

    return sorted(seen.values(), key=lambda x: (-x["discount_pct"], x["price"]))[:limit]


# ====================================================================
# ДОСТАВКА (из нашей системы)
# ====================================================================

def np_delivery_prices(weight_kg: float = 2.0, floor: int = 1) -> list[dict]:
    """НП: курьер и отделение."""
    w_tariff = [(0.5, 55), (1.0, 60), (2.0, 70), (5.0, 85), (10.0, 105)]
    c_tariff = [(0.5, 75), (1.0, 85), (2.0, 95), (5.0, 110), (10.0, 135)]

    w_cost = next((p for kg, p in w_tariff if weight_kg <= kg), 105)
    c_cost = next((p for kg, p in c_tariff if weight_kg <= kg), 135)
    if floor > 2:
        c_cost += (floor - 2) * 15

    return [
        {"name": "НП Відділення", "cost": w_cost, "days": 1},
        {"name": "НП Кур'єр на дім", "cost": c_cost, "days": 1},
    ]


# ====================================================================
# КОНФИГ
# ====================================================================

def load_config() -> dict:
    path = SCRIPT_DIR / "shopping_list.json"
    cfg = {}
    if path.exists():
        cfg = json.loads(path.read_text(encoding="utf-8"))
    # env vars override file values (for CI/GitHub Actions)
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        cfg["telegram_bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_CHAT_ID"):
        cfg["telegram_chat_id"] = int(os.environ["TELEGRAM_CHAT_ID"])
    return cfg


# ====================================================================
# ФОРМАТ ОТЧЁТА
# ====================================================================

def format_report(promos: list[dict], products: dict[str, list[dict]], city: str, address: str) -> str:
    """Единый красивый отчёт для Telegram."""
    now = datetime.now()
    hour = now.hour
    tod = "🌅 УТРЕННИЙ" if hour < 12 else ("☀️ ДНЕВНОЙ" if hour < 17 else "🌙 ВЕЧЕРНИЙ")
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    parts = [
        f"🛒 <b>{tod} ОБЗОР</b>",
        f"📅 {days[now.weekday()]}, {now.day:02d}.{now.month:02d} · {now.strftime('%H:%M')}",
        f"📍 {address}",
        "─" * 28,
    ]

    # === СКИДКИ (Zakaz.ua API) ===
    if promos:
        parts.append("\n🔥 <b>СКИДКИ ДНЯ В КИЕВЕ</b>")
        parts.append("─" * 28)
        for d in promos[:10]:
            due = f" · до {d['due_date']}" if d.get("due_date") else ""
            parts.append(
                f"<b>−{d['discount_pct']}%</b>  {d['price']:.0f} ₴ "
                f"<s>{d['old_price']:.0f}</s>  "
                f"<a href='{d['url']}'>{d['title'][:45]}</a>\n"
                f"   🏪 {d['store']}{due}"
            )

    # === ПОИСК ПРОДУКТОВ ===
    if products:
        parts.append("\n🔍 <b>ЦЕНЫ НА ПРОДУКТЫ</b>")
        parts.append("─" * 28)
        for product, deals in products.items():
            if deals:
                best = deals[0]
                card = [f"<b>{product}</b>"]
                if best.get('url'):
                    card.append(f"  💰 <b>{best['price']:.0f} ₴</b> — {best['store']}  "
                               f"<a href='{best['url']}'>🛒 купить</a>")
                else:
                    card.append(f"  💰 <b>{best['price']:.0f} ₴</b> — {best['store']}")
                others = [d for d in deals[1:4] if d['store'] != best['store'] and d.get('url')]
                if others:
                    for o in others[:3]:
                        card.append(f"  • {o['store']}: {o['price']:.0f} ₴  "
                                   f"<a href='{o['url']}'>→</a>")
                parts.append("\n".join(card))
            else:
                parts.append(f"  ❌ {product} — не найдено")

    # === ДОСТАВКА ===
    np = np_delivery_prices(2.0, 1)
    parts.append(f"\n🚚 <b>НОВАЯ ПОШТА</b>")
    parts.append("─" * 28)
    for opt in np:
        parts.append(f"  {opt['name']}: <b>{opt['cost']:.0f} ₴</b> (~{opt['days']} дн)")

    parts.append(f"\n{'─' * 28}")
    parts.append(f"🤖 Следующий обзор: {_next_run(hour)}")

    return "\n".join(parts)


def _next_run(hour: int) -> str:
    for h in [9, 13, 18]:
        if h > hour:
            return f"{h}:00"
    return "09:00 (завтра)"


# ====================================================================
# АВТО-РАННЕР
# ====================================================================

async def run_cycle(test: bool = False):
    """Один цикл: Zakaz.ua промо + поиск продуктов + доставка."""
    config = load_config()
    city = config.get("city", "Киев")
    addr = config.get("address", {})
    street = addr.get("street", "вул. Б. Антоненка-Давидовича")
    if not street.startswith("вул.") and not street.startswith("вулиця"):
        street = f"вул. {street}"
    full_addr = f"{street}, {addr.get('building', '1')}"
    shop_list = config.get("categories", {})

    print(f"🛒 Цикл запущен...")

    # 1. Zakaz.ua API — скидки (быстро, без браузера)
    promos = await zakaz_top_promos("all", min_pct=25, limit=15)

    # 2. Поиск продуктов из shopping_list (ВСЕ товары + rate-limit safety)
    products = {}
    if not test and shop_list:
        flat = []
        for cat_name, cat_items in shop_list.items():
            for item in cat_items:
                flat.append(item)
        # Cap at 20 to avoid hammering Zakaz.ua API
        flat = flat[:20]
        errors = 0
        for item in flat:
            if errors >= 3:
                break
            try:
                results = await zakaz_search_product(item, limit=3)
                products[item] = results
                await asyncio.sleep(0.35)
            except Exception:
                errors += 1
                products[item] = []
    elif test:
        products["молоко 1л"] = await zakaz_search_product("молоко 1л", limit=5)
        products["яйца 10шт"] = await zakaz_search_product("яйца 10шт", limit=5)

    # 3. Формат + отправка
    report = format_report(promos, products, city, full_addr)
    return report


async def send_telegram(report: str, bot_token: str, chat_id: int, max_retries=3) -> bool:
    """Send with retry. Falls back to httpx if aiogram unavailable (CI)."""
    if not bot_token:
        print("⚠️ BOT_TOKEN не задан")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async def _send_chunk(text: str, attempt: int = 0) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(url, json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }, timeout=15)
                if r.status_code == 200:
                    return True
                if r.status_code == 429:
                    wait = r.json().get("parameters", {}).get("retry_after", 3)
                    await asyncio.sleep(wait)
                    if attempt < max_retries:
                        return await _send_chunk(text, attempt + 1)
                return False
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                return await _send_chunk(text, attempt + 1)
            print(f"❌ Telegram (attempt {attempt+1}): {e}")
            return False

    try:
        chunks = [report] if len(report) <= 4000 else [
            report[i:i+3800] for i in range(0, len(report), 3800)
        ]
        ok = True
        for i, chunk in enumerate(chunks):
            prefix = f"📄 Часть {i+1}\n\n" if i > 0 else ""
            ok = ok and await _send_chunk(prefix + chunk)
            if i + 1 < len(chunks):
                await asyncio.sleep(0.5)
        return ok
    except Exception as e:
        print(f"❌ Telegram: {e}")
        return False


async def main_loop():
    config = load_config()
    schedule = config.get("schedule_hours", SCHEDULE_HOURS)
    bot_token = config.get("telegram_bot_token", "")
    chat_id = config.get("telegram_chat_id", 0)

    print(f"🤖 Unified Auto Shopper запущен")
    print(f"🕐 Расписание: {', '.join(f'{h}:00' for h in schedule)}")
    print(f"⚡ Zakaz.ua API (без браузера) + НП доставка")

    last_hour = None
    while True:
        now = datetime.now(KYIV_TZ)
        h = now.hour
        if h in schedule and h != last_hour:
            last_hour = h
            print(f"\n🚀 ЗАПУСК: {now.strftime('%H:%M')}")
            try:
                report = await run_cycle()
                print(report[:500])
                (SCRIPT_DIR / "last_report.html").write_text(report, encoding="utf-8")
                await send_telegram(report, bot_token, chat_id)
            except Exception as e:
                print(f"❌ Ошибка: {e}")
            print("✅ Готово")

        next_h = next((x for x in schedule if x > h), schedule[0])
        wait = ((next_h - h) % 24) * 60 - now.minute
        if wait <= 0: wait += 24 * 60
        await asyncio.sleep(min(wait * 60, 60))


async def run_once(test: bool = False):
    report = await run_cycle(test=test)
    print("\n" + report)

    config = load_config()
    bt = config.get("telegram_bot_token", "")
    cid = config.get("telegram_chat_id", 0)
    if bt and cid:
        await send_telegram(report, bt, cid)
    (SCRIPT_DIR / "last_report.html").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    import atexit
    if "--loop" in sys.argv:
        acquire_lock()
        atexit.register(release_lock)
        try:
            asyncio.run(main_loop())
        finally:
            release_lock()
    elif "--test" in sys.argv:
        asyncio.run(run_once(test=True))
    else:
        asyncio.run(run_once())
