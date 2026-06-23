"""
Zakaz.ua grocery-deal source — 100% FREE, no API key, no auth.

Zakaz.ua powers online delivery for major Kyiv chains (Novus, Auchan, Metro,
Megamarket, Ekomarket, ...) and exposes a public JSON API with current discounts,
including the percentage off, old price and how long the promo lasts.

We use it to answer: "what is heavily discounted in Kyiv stores right now?"
— food and hygiene products at the bottom of the market.
"""
from __future__ import annotations

import httpx

from app.pricing.deal_models import PromoDeal
from app.utils.logger import logger

BASE = "https://stores-api.zakaz.ua"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "uk",
}

# Category groups (Zakaz category ids are shared across chains for the common ones).
FOOD_CATEGORIES = [
    "dairy-and-eggs", "fruits-and-vegetables", "meat-fish-poultry",
    "snacks-and-sweets", "packets-cereals", "drinks", "bakery",
    "tins-jars-cooking", "frozen", "crisps-and-snacks", "hot-drinks-novus",
]
HYGIENE_CATEGORIES = [
    "personal-hygiene", "household-chemicals", "household-and-cleaning", "babies",
]
ALL_CATEGORIES = FOOD_CATEGORIES + HYGIENE_CATEGORIES

# Default Kyiv stores to scan (chain -> store_id). Novus + Auchan give broad coverage.
DEFAULT_KYIV_STORES = {
    "novus": "482010105",
    "auchan": "48246401",
    "metro": "48215610",
}


async def _get_json(client: httpx.AsyncClient, url: str, chain: str):
    try:
        r = await client.get(url, headers={**_HEADERS, "x-chain": chain}, timeout=25)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        logger.debug("zakaz GET failed {}: {}", url, e)
        return None


async def list_kyiv_stores() -> dict[str, list[dict]]:
    """Return active Kyiv stores grouped by retail chain."""
    out: dict[str, list[dict]] = {}
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{BASE}/stores/", headers=_HEADERS, timeout=25)
            stores = r.json()
        except Exception as e:
            logger.warning("zakaz list_kyiv_stores failed: {}", e)
            return out
    for s in stores:
        if s.get("city") == "kiev" and s.get("is_active"):
            out.setdefault(s["retail_chain"], []).append(s)
    return out


async def fetch_store_discounts(
    chain: str,
    store_id: str,
    store_name: str,
    *,
    categories: list[str] | None = None,
    max_pages: int = 2,
    min_pct: int = 0,
) -> list[PromoDeal]:
    """Fetch discounted products for one store across the given categories."""
    categories = categories or ALL_CATEGORIES
    deals: list[PromoDeal] = []
    async with httpx.AsyncClient() as client:
        for cid in categories:
            for page in range(1, max_pages + 1):
                url = f"{BASE}/stores/{store_id}/categories/{cid}/products/?page={page}"
                data = await _get_json(client, url, chain)
                if not data or not data.get("results"):
                    break
                for p in data["results"]:
                    d = p.get("discount") or {}
                    if not (d.get("status") and d.get("value")):
                        continue
                    pct = int(d["value"])
                    if pct < min_pct:
                        continue
                    deals.append(PromoDeal(
                        store_chain=chain,
                        store_name=store_name,
                        title=p.get("title", "").strip(),
                        price=round(p.get("price", 0) / 100, 2),
                        old_price=round((d.get("old_price") or 0) / 100, 2),
                        discount_pct=pct,
                        category=cid,
                        url=p.get("web_url", ""),
                        due_date=d.get("due_date"),
                        image=(p.get("img") or {}).get("s") if isinstance(p.get("img"), dict) else None,
                    ))
    return deals


async def find_promos(
    *,
    group: str = "all",          # "all" | "food" | "hygiene"
    min_pct: int = 30,
    stores: dict[str, str] | None = None,
    limit: int = 25,
) -> list[PromoDeal]:
    """
    Aggregate the biggest current discounts across default Kyiv stores.
    Returns deals sorted by discount % (highest first), de-duplicated by title.
    """
    cats = {"food": FOOD_CATEGORIES, "hygiene": HYGIENE_CATEGORIES}.get(group, ALL_CATEGORIES)
    stores = stores or DEFAULT_KYIV_STORES

    all_deals: list[PromoDeal] = []
    for chain, sid in stores.items():
        try:
            all_deals += await fetch_store_discounts(
                chain, sid, chain.capitalize(), categories=cats, min_pct=min_pct
            )
        except Exception as e:
            logger.warning("zakaz store {} failed: {}", chain, e)

    # de-dup by (title, chain), keep the biggest discount
    seen: dict[tuple, PromoDeal] = {}
    for d in all_deals:
        key = (d.title.lower(), d.store_chain)
        if key not in seen or d.discount_pct > seen[key].discount_pct:
            seen[key] = d

    deals = sorted(seen.values(), key=lambda x: (-x.discount_pct, x.price))
    logger.info("zakaz find_promos group={} min={}%: {} deals", group, min_pct, len(deals))
    return deals[:limit]
