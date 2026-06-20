"""
Full monitoring engine — Playwright → parsing → AI → scoring → Telegram.
Runs inside Celery task or asyncio loop.
"""
import json
import os
from datetime import datetime
from app.utils.logger import logger
from app.crawler.browser import OLXBrowser
from app.crawler.parser import fetch_listings, parse_ad
from app.scoring.deal_score import calculate_deal_score
from app.scoring.risk_score import calculate_risk_score
from app.scoring.market_price import estimate_market_price
from app.scoring.ai_analyzer import analyze_listing_with_ai
from app.services.notifier import send_ad_notification
from app.services.learning import get_deal_threshold_modifier
from app.services.price_alerts import track_price
from app.services.ai_learning import record_prediction
from app.bot.telegram_bot import bot
from config import settings

WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "app", "data", "watchlist.json",
)


def load_watchlist() -> list[dict]:
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load watchlist: %s", e)
    return []


async def process_watch_item(
    browser: OLXBrowser,
    item: dict,
    session,
    AdModel,
    SnapModel,
    sent_count: int,
) -> int:
    """Process one watchlist item: fetch listings → score → notify."""
    search_url = item.get("search_url", "")
    max_price = item.get("normal_price_range", [0, 999999])[1] * 1.3
    name = item.get("name", "?")
    category = item.get("category", "general")
    watch_id = item.get("id", "")
    keywords = item.get("keywords", [])
    normal_range = item.get("normal_price_range", [0, 0])

    logger.info("Scanning: %s", name)

    listings = await fetch_listings(browser, search_url, max_price, max_scrolls=3)
    logger.info("Found %d items for %s", len(listings), name)

    for ad_data in listings:
        if sent_count >= 3:
            break

        try:
            existing = session.query(AdModel).filter(
                AdModel.url == ad_data["url"]
            ).first()
            if existing:
                continue

            ad_data = await parse_ad(browser, ad_data["url"])
            if not ad_data:
                continue

            title = ad_data.get("title", "")
            description = ad_data.get("description", "")
            price = ad_data.get("price", 0)

            session.add(SnapModel(
                watch_item_id=watch_id,
                title=title,
                price=price,
                url=ad_data["url"],
            ))
            session.flush()

            ai_result = await analyze_listing_with_ai(title, description, price)

            market_median = sum(normal_range) / 2 if normal_range[1] > 0 else price * 1.5
            deal_score, profit = calculate_deal_score(
                price=price,
                market_median=market_median,
                watch_item=item,
                title=title,
                description=description,
                image_url=ad_data.get("photos", [None])[0],
                published_at=datetime.now(),
                ai_condition_score=ai_result.get("condition_score"),
            )
            risk_score = calculate_risk_score(
                price=price,
                market_median=market_median,
                title=title,
                description=description,
                image_url=ad_data.get("photos", [None])[0],
                watch_item=item,
                ai_defects=ai_result.get("defects"),
            )

            ad = AdModel(
                olx_id=ad_data["url"].split("/")[-1][:64],
                title=ai_result.get("product_name_corrected", title),
                price=price,
                url=ad_data["url"],
                location=ad_data.get("seller_name", ""),
                description=description,
                image_url=ad_data.get("photos", [None])[0] if ad_data.get("photos") else None,
                category=category,
                watch_item_id=watch_id,
                deal_score=deal_score,
                analysis_json=ai_result,
                risk_score=risk_score,
                estimated_market_price=market_median,
                estimated_profit=profit,
                status="new",
            )
            session.add(ad)
            session.flush()

            modifier = get_deal_threshold_modifier(watch_id)
            effective_threshold = settings.deal_score_threshold + modifier

            if deal_score >= effective_threshold and risk_score <= settings.risk_score_max and profit >= item.get("min_profit", settings.default_min_profit):
                ad.status = "ready"
                ad.sent_to_telegram = True
                sent_count += 1
                # Send to Telegram
                try:
                    from app.bot.telegram_bot import bot
                    await send_ad_notification(bot, settings.telegram_chat_id, ad, item)
                    # Record AI prediction for self-learning
                    record_prediction(session, ad.id, watch_id, ai_result)
                    logger.info("Notification sent: %s", ad.title[:50])
                except Exception as e:
                    logger.warning("Telegram send failed (bot may not be polling): %s", e)
            else:
                ad.status = "filtered"

            session.commit()

        except Exception as e:
            logger.error("Error processing ad %s: %s", ad_data.get("url", "?"), e)
            session.rollback()

    return sent_count


async def run_full_cycle():
    """Run one full monitoring cycle: all watchlist items → score → notify."""
    browser = OLXBrowser(headless=True)
    await browser.start()

    from app.storage.database import SyncSession
    from app.storage.models import Ad, MarketSnapshot

    session = SyncSession()
    try:
        watchlist = load_watchlist()
        if not watchlist:
            logger.warning("Watchlist is empty")
            return

        logger.info("Starting full cycle: %d items", len(watchlist))
        sent = 0
        for item in watchlist:
            sent = await process_watch_item(browser, item, session, Ad, MarketSnapshot, sent)
            if sent >= 3:
                logger.info("Sent 3 items this cycle, stopping.")
                break

        logger.info("Full cycle done. Sent: %d", sent)
    finally:
        session.close()
        await browser.close()
