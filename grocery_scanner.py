"""
Grocery Price Scanner v2 — 4 магазина с Playwright JS-рендерингом.

Магазины:
  Zakaz.ua   — агрегатор (Metro+Auchan+Novus+MegaMarket)
  Silpo      — доставка по Киеву (shop.silpo.ua)
  MAUDAU     — онлайн-гипермаркет со скидками
  ATB        — дискаунтер (через API)
"""

import httpx
import re
import asyncio
import json
from dataclasses import dataclass, field
from typing import Optional
from bs4 import BeautifulSoup


@dataclass
class GroceryItem:
    name: str
    quantity: str = "1 шт"


@dataclass
class StoreOffer:
    store: str
    product: str
    price: float
    old_price: float = 0.0
    discount_pct: int = 0
    url: str = ""
    available: bool = True
    delivery_cost: float = 0.0
    delivery_days: int = 1


@dataclass
class ShoppingResult:
    product: str
    offers: list[StoreOffer] = field(default_factory=list)
    min_price: float = 0.0
    min_store: str = ""
    avg_price: float = 0.0
    savings: float = 0.0

    @property
    def best_offer(self) -> Optional[StoreOffer]:
        if not self.offers:
            return None
        return min(self.offers, key=lambda o: o.price)


# === УТИЛИТЫ ===

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 Chrome/124.0.0.0",
    "Accept-Language": "uk-UA,uk;q=0.9",
}


def _parse_price(text: str) -> float:
    text = re.sub(r"[^\d.,]", "", text.replace(" ", "").replace("\xa0", ""))
    text = text.replace(",", ".")
    try: return float(text)
    except ValueError: return 0.0


async def _fetch(url: str, timeout: int = 15) -> Optional[str]:
    """httpx → Playwright fallback."""
    try:
        async with httpx.AsyncClient(timeout=float(timeout), follow_redirects=True) as c:
            r = await c.get(url, headers=COMMON_HEADERS)
            if r.status_code == 200 and _has_products(r.text):
                return r.text
    except Exception:
        pass
    try:
        from js_fetch import fetch_js
        return await fetch_js(url, timeout=timeout * 1000)
    except Exception:
        return None


def _has_products(html: str) -> bool:
    return len(re.findall(r'\d{2,6}[.,]\d{2}\s*(?:₴|грн)', html)) >= 2


# ====================================================================
# ZAKAZ.UA — главный агрегатор (Metro+Auchan+Novus)
# ====================================================================

async def search_zakaz(product: str) -> list[StoreOffer]:
    query = product.replace(" ", "%20")
    # Zakaz.ua = Next.js SPA — всегда Playwright
    from js_fetch import fetch_js
    html = await fetch_js(f"https://zakaz.ua/uk/search/?q={query}", timeout=15000)
    if not html: return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    for a_tag in soup.find_all("a", href=re.compile(r"/products?/")):
        try:
            full_text = a_tag.get_text(strip=True)
            if len(full_text) < 10: continue

            pm = re.search(r'(\d+\.?\d*)₴', full_text)
            if not pm: continue

            price = float(pm.group(1))
            name = full_text[:pm.start()].strip()
            if not name: continue

            link = a_tag.get("href", "")
            if link.startswith("/"): link = f"https://zakaz.ua{link}"

            results.append(StoreOffer(store="Zakaz.ua", product=name,
                          price=price, url=link, delivery_cost=59.0, delivery_days=1))
        except Exception:
            continue
    return results


# ====================================================================
# SILPO — shop.silpo.ua (custom element <shop-silpo-common-product-card>)
# ====================================================================

async def search_silpo(product: str) -> list[StoreOffer]:
    query = product.replace(" ", "+")
    from js_fetch import fetch_js
    html = await fetch_js(f"https://shop.silpo.ua/catalog/search?q={query}", timeout=15000)
    if not html: return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Silpo: article.product-card содержит:
    #   <h3 class="product-card__title">Назва</h3>
    #   <div class="product-card-price__displayPrice">19.40 грн</div>
    #   <div class="product-card-price__displayOldPrice">22.90 грн</div>
    #   <div class="product-card-price__sale">- 15%</div>
    for card in soup.find_all("article", class_="product-card"):
        try:
            title_tag = card.find("h3", class_="product-card__title")
            price_tag = card.find(class_="product-card-price__displayPrice")
            old_tag = card.find(class_="product-card-price__displayOldPrice")
            sale_tag = card.find(class_="product-card-price__sale")
            link_tag = card.find("a", class_="product-card__link")

            if not title_tag or not price_tag:
                continue

            name = title_tag.get_text(strip=True)
            price = _parse_price(price_tag.get_text(strip=True))
            old_price = _parse_price(old_tag.get_text(strip=True)) if old_tag else 0.0
            discount = int(re.findall(r'\d+', sale_tag.get_text(strip=True))[0]) if sale_tag else 0
            link = link_tag.get("href", "") if link_tag else ""
            if link.startswith("/"): link = f"https://shop.silpo.ua{link}"

            results.append(StoreOffer(
                store="Silpo", product=name, price=price,
                old_price=old_price, discount_pct=discount,
                url=link, delivery_cost=79.0, delivery_days=1,
            ))
        except Exception:
            continue
    return results


# ====================================================================
# MAUDAU — data-testid селекторы
# ====================================================================

async def search_maudau(product: str) -> list[StoreOffer]:
    query = product.replace(" ", "+")
    html = await _fetch(f"https://maudau.com.ua/search?q={query}", timeout=15)
    if not html: return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    for item in soup.find_all(attrs={"data-testid": "productItem"}):
        try:
            name_tag = item.find(attrs={"data-testid": "productName"})
            price_tag = item.find(attrs={"data-testid": "productFullPrice"})
            old_tag = item.find(attrs={"data-testid": "productOldPrice"})
            link_tag = item.find("a", href=True)

            if not name_tag or not price_tag: continue

            name = name_tag.get_text(strip=True)
            price = _parse_price(price_tag.get_text(strip=True))
            old_price = _parse_price(old_tag.get_text(strip=True)) if old_tag else 0.0
            discount = int((1 - price / old_price) * 100) if old_price > price else 0

            link = link_tag.get("href", "") if link_tag else ""
            if link.startswith("/"): link = f"https://maudau.com.ua{link}"

            results.append(StoreOffer(
                store="MAUDAU", product=name, price=price,
                old_price=old_price, discount_pct=discount,
                url=link, delivery_cost=69.0, delivery_days=2,
            ))
        except Exception:
            continue
    return results


# ====================================================================
# ATB — через API / JSON в script
# ====================================================================

async def search_atb(product: str) -> list[StoreOffer]:
    query = product.replace(" ", "+")
    # ATB = React SPA — всегда Playwright
    from js_fetch import fetch_js
    html = await fetch_js(f"https://atbmarket.com/search?q={query}", timeout=15000)
    if not html: return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # ATB грузит данные через API — ищем JSON в <script type="application/json">
    for script in soup.find_all("script", type="application/json"):
        try:
            data = json.loads(script.string or "")
            _extract_atb_json(data, results)
        except (json.JSONDecodeError, TypeError):
            continue

    # Fallback: ищем __NEXT_DATA__ или __INITIAL_STATE__
    if not results:
        for script in soup.find_all("script"):
            txt = script.string or ""
            if '"products"' in txt or '"items"' in txt:
                try:
                    # Extract JSON between curly braces
                    json_match = re.search(r'\{.*"products?".*\}', txt, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group())
                        _extract_atb_json(data, results)
                except Exception:
                    continue

    return results


def _extract_atb_json(data: dict, results: list):
    """Рекурсивный поиск продуктов в JSON ATB."""
    if isinstance(data, dict):
        if "name" in data and "price" in data:
            name = str(data.get("name", data.get("title", "")))
            price_val = data.get("price", data.get("priceValue", 0))
            if isinstance(price_val, (int, float)) and price_val > 0:
                results.append(StoreOffer(
                    store="ATB", product=name, price=float(price_val),
                ))
            return
        for v in data.values():
            _extract_atb_json(v, results)
    elif isinstance(data, list):
        for item in data[:20]:
            _extract_atb_json(item, results)


# ====================================================================
# ГЛАВНЫЙ АГРЕГАТОР
# ====================================================================

STORES = [
    ("Zakaz.ua", search_zakaz),
    ("Silpo", search_silpo),
    ("MAUDAU", search_maudau),
]


async def find_cheapest(product: str) -> ShoppingResult:
    tasks = [fn(product) for _, fn in STORES]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    all_offers: list[StoreOffer] = []
    for r in raw:
        if isinstance(r, list): all_offers.extend(r)

    # Фильтр: только товары содержащие поисковый запрос в названии
    query_words = product.lower().split()
    relevant = []
    for o in all_offers:
        name_lower = o.product.lower()
        if any(w in name_lower for w in query_words):
            relevant.append(o)

    # Если отфильтровалось в 0 — вернуть всё
    if not relevant:
        relevant = all_offers

    if not relevant:
        return ShoppingResult(product=product)

    relevant.sort(key=lambda o: o.price)

    # Экономия: лучшая vs худшая (без выбросов — макс 3x от медианы)
    median_idx = len(relevant) // 2
    median_price = sorted(o.price for o in relevant)[median_idx]
    cap = median_price * 3 if median_price > 0 else 999999
    normal_prices = [o for o in relevant if o.price <= cap]

    if normal_prices:
        cheapest = normal_prices[0]
        most_expensive = normal_prices[-1]
        avg = sum(o.price for o in normal_prices) / len(normal_prices)
        savings = most_expensive.price - cheapest.price
    else:
        cheapest = relevant[0]
        avg = cheapest.price
        savings = 0

    return ShoppingResult(
        product=product, offers=relevant,
        min_price=cheapest.price, min_store=cheapest.store,
        avg_price=round(avg, 2),
        savings=round(savings, 2),
    )


async def find_cheapest_basket(items: list[GroceryItem]) -> dict:
    tasks = [find_cheapest(item.name) for item in items]
    results = await asyncio.gather(*tasks)

    store_totals: dict[str, float] = {}
    for r in results:
        if r.best_offer:
            s = r.best_offer.store
            store_totals[s] = store_totals.get(s, 0) + r.best_offer.price

    total_min = sum(r.min_price for r in results)
    best_store = min(store_totals, key=store_totals.get) if store_totals else "--"

    return {
        "items": list(results),
        "total_min": total_min,
        "best_store": best_store,
        "store_totals": store_totals,
    }
