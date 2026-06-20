"""
Search API — immediate OLX search + AI analysis.
User types a product → Playwright scans → AI analyzes → returns results.
"""
import asyncio
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.crawler.browser import OLXBrowser
from app.crawler.parser import fetch_listings, parse_ad
from app.scoring.deal_score import calculate_deal_score
from app.scoring.risk_score import calculate_risk_score
from app.scoring.ai_analyzer import analyze_listing_with_ai
from app.scoring.market_price import estimate_market_price
from app.services.price_alerts import track_price
from app.utils.logger import logger

router = APIRouter(prefix="/api", tags=["search"])


def _build_search_url(query: str, max_price: int = 0) -> str:
    """Build OLX search URL from query."""
    q = query.lower().replace(" ", "-")
    url = f"https://www.olx.ua/uk/list/q-{q}/?search%5Border%5D=created_at%3Adesc"
    if max_price > 0:
        url += f"&search%5Bfilter_float_price%3Ato%5D={max_price}"
    return url


def _make_watch_item(query: str) -> dict:
    """Build minimal watch_item dict for scoring functions."""
    return {
        "id": query.lower().replace(" ", "_"),
        "name": query,
        "category": "other",
        "keywords": [query.lower()],
        "normal_price_range": [0, 999999],
        "max_green_price": 0,
        "min_profit": 0,
        "bad_words": [],
    }


def _format_result(ad_data: dict, analysis: dict, deal_score: int, risk_score: int) -> dict:
    """Format a single result for the API response."""
    price = ad_data.get("price", 0)
    erp = analysis.get("estimated_resell_price", 0)
    profit = erp - price if erp > price else 0
    profit_pct = (profit / price * 100) if price > 0 else 0

    badges = []
    if profit_pct >= 40:
        badges.append("🔥 МЕГА-СДЕЛКА")
    elif profit_pct >= 25:
        badges.append("💎 ОТЛИЧНО")
    elif profit_pct >= 15:
        badges.append("✅ ХОРОШО")
    if risk_score <= 20:
        badges.append("🛡 Безопасно")
    elif risk_score >= 60:
        badges.append("⚠️ Риск")

    return {
        "title": ad_data.get("title", "")[:150],
        "price": price,
        "url": ad_data.get("url", ""),
        "photo": (ad_data.get("photos") or [None])[0],
        "seller": ad_data.get("seller_name", ""),
        "deal_score": deal_score,
        "risk_score": risk_score,
        "badges": badges,
        "profit_pct": round(profit_pct, 0),
        "profit": int(profit),
        "ai": {
            "condition": analysis.get("condition_type", "used_good"),
            "condition_score": analysis.get("condition_score", 50),
            "resell_price": erp,
            "net_profit": analysis.get("net_profit", int(profit * 0.85)),
            "bargain": analysis.get("bargain_price", int(price * 0.85)),
            "liquidity": analysis.get("liquidity", "normal"),
            "urgency": analysis.get("urgency", "medium"),
            "saturation": analysis.get("market_saturation", "medium"),
            "seller_risk": analysis.get("seller_risk", "low"),
            "seasonality": analysis.get("seasonality", "normal"),
            "confidence": analysis.get("confidence", "medium"),
            "defects": analysis.get("defects", []),
            "verdict": analysis.get("verdict", "")[:300],
        },
    }


@router.get("/search")
async def search_olx(
    q: str = Query(..., description="Product name to search"),
    max_price: float = Query(0, description="Max price filter"),
    max_results: int = Query(6, description="Max results to return"),
):
    """
    Search OLX immediately and get AI-analyzed results.
    Example: /api/search?q=iphone+12&max_price=10000
    """
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Search query too short")

    query = q.strip()
    url = _build_search_url(query, int(max_price))
    watch_item = _make_watch_item(query)

    logger.info("Search: %s (URL: %s)", query, url[:80])

    browser = OLXBrowser(headless=True)
    await browser.start()

    try:
        listings = await fetch_listings(browser, url, float(max_price or 999999), max_scrolls=3)
        listings = listings[:max_results]
        logger.info("Found %d items", len(listings))

        results = []
        for item in listings:
            try:
                ad_data = await parse_ad(browser, item["url"])
                if not ad_data:
                    continue

                analysis = await analyze_listing_with_ai(
                    ad_data.get("title", ""),
                    ad_data.get("description", ""),
                    ad_data.get("price", 0),
                )

                market_median = ad_data.get("price", 0) * 1.3
                deal_score, _ = calculate_deal_score(
                    price=ad_data.get("price", 0),
                    market_median=market_median,
                    watch_item=watch_item,
                    title=ad_data.get("title", ""),
                    description=ad_data.get("description", ""),
                    image_url=(ad_data.get("photos") or [None])[0],
                    ai_condition_score=analysis.get("condition_score"),
                )
                risk_score = calculate_risk_score(
                    price=ad_data.get("price", 0),
                    market_median=market_median,
                    title=ad_data.get("title", ""),
                    description=ad_data.get("description", ""),
                    image_url=(ad_data.get("photos") or [None])[0],
                    watch_item=watch_item,
                    ai_defects=analysis.get("defects"),
                )

                results.append(_format_result(ad_data, analysis, deal_score, risk_score))

            except Exception as e:
                logger.warning("Search item error: %s", e)

        return {
            "query": query,
            "count": len(results),
            "results": results,
            "ai_features": [
                "condition_type", "condition_score", "estimated_resell_price",
                "net_profit", "bargain_price", "liquidity", "urgency",
                "market_saturation", "seller_risk", "seasonality",
                "confidence", "defects", "verdict",
                "deal_score", "risk_score",
            ],
        }

    except Exception as e:
        logger.error("Search failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await browser.close()
