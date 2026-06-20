import os
import json
from datetime import datetime
from aiogram import Bot

from config import settings
from app.olx.scraper import fetch_page
from app.olx.parser import parse_listings_page, parse_details_page
from app.olx.url_builder import clean_and_build_url
from app.storage.database import db_session
from app.storage.models import Ad, MarketSnapshot
from app.storage.repositories import AdRepository, MarketSnapshotRepository, CategoryStatsRepository
from app.scoring.market_price import estimate_market_price
from app.scoring.deal_score import calculate_deal_score
from app.scoring.risk_score import calculate_risk_score
from app.scoring.ai_analyzer import analyze_listing_with_ai
from app.services.learning import get_deal_threshold_modifier, get_pause_state
from app.services.notifier import send_ad_notification
from app.utils.text import get_similarity_ratio
from app.utils.logger import logger
from app.scoring.text_analyzer import load_global_bad_words

def load_watchlist() -> list[dict]:
    """
    Loads monitored items definitions.
    """
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "watchlist.json"
    )
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load watchlist.json: {}", e)
    return []

async def run_monitoring_cycle(bot: Bot):
    """
    Main monitoring cycle executed by the scheduler.
    """
    if get_pause_state():
        logger.info("Monitoring is currently paused. Skipping cycle.")
        return
        
    logger.info("Starting monitoring cycle...")
    # Auto-health check: приостановить мёртвые позиции
    try:
        from app.services.watchlist_health import auto_cleanup
        with db_session() as session:
            changes = auto_cleanup(session)
            for c in changes:
                logger.info("Auto: {} → {} ({})", c["name"], c["action"], c["reason"])
    except Exception as e:
        logger.debug("Health check: {}", e)

    watchlist = load_watchlist()
    if not watchlist:
        logger.warning("Watchlist is empty. Add items to watchlist.json.")
        return
        
    sent_count_this_cycle = 0
    
    for item in watchlist:
        if get_pause_state():
            logger.info("Monitoring paused during active cycle. Aborting.")
            break
            
        watch_item_id = item["id"]
        category = item["category"]
        keywords = item["keywords"]
        normal_range = item["normal_price_range"]
        min_profit_threshold = item.get("min_profit", settings.default_min_profit)
        search_url = clean_and_build_url(item["search_url"])
        
        # Load global bad words once per watch item (not per listing)
        global_bad_words = load_global_bad_words()
        item_bad_words = [bw.lower() for bw in item.get("bad_words", [])]
        all_bad_words = set(item_bad_words) | set(bw.lower() for bw in global_bad_words)
        
        # Minimum price floor: item must cost at least 15% of normal market minimum
        # This immediately eliminates 100-500 UAH accessories, cases, chargers, etc.
        price_floor = normal_range[0] * 0.15
        
        logger.info("Monitoring watch item: {} (ID: {})", item["name"], watch_item_id)
        
        # 1. Fetch listing index page
        html = await fetch_page(search_url)
        if not html:
            logger.warning("Could not fetch page for {}", watch_item_id)
            continue
            
        scraped_ads = parse_listings_page(html)
        logger.info("Parsed {} items from search results", len(scraped_ads))
        
        # Process up to top 15 parsed ads (to keep it light and responsive)
        for scraped in scraped_ads[:15]:
            try:
                # 2. Add to market snapshots to build history for pricing estimation
                with db_session() as session:
                    snapshot = MarketSnapshot(
                        watch_item_id=watch_item_id,
                        title=scraped.title,
                        price=scraped.price,
                        url=scraped.url
                    )
                    MarketSnapshotRepository.add(session, snapshot)
                    
                    # 3. Check if Ad already parsed previously (exact ID match)
                    existing = AdRepository.get_by_olx_id(session, scraped.olx_id)
                    if existing:
                        continue
                    
                    # Duplicate check: Title similarity match (>85%) against last 30 ads
                    recent_ads = (
                        session.query(Ad)
                        .filter(Ad.watch_item_id == watch_item_id)
                        .order_by(Ad.created_at.desc())
                        .limit(30)
                        .all()
                    )
                    
                    is_title_duplicate = False
                    for old_ad in recent_ads:
                        if get_similarity_ratio(scraped.title, old_ad.title) >= 0.85:
                            is_title_duplicate = True
                            break
                            
                    if is_title_duplicate:
                        ad = Ad(
                            olx_id=scraped.olx_id,
                            title=scraped.title,
                            price=scraped.price,
                            url=scraped.url,
                            location=scraped.location,
                            category=category,
                            watch_item_id=watch_item_id,
                            status="filtered_duplicate"
                        )
                        AdRepository.add(session, ad)
                        logger.debug("Filtered duplicate ad by title: '{}'", scraped.title)
                        continue
                        
                # 4. Primary filter: keywords, price range, and bad words in TITLE
                title_lower = scraped.title.lower()
                kw_match = any(kw.lower() in title_lower for kw in keywords)
                
                # Price must be within realistic range:
                #   MIN: at least 15% of normal market min (blocks 100 UAH accessories)
                #   MAX: no more than 130% of normal market max (ignores overpriced resellers)
                price_ok = (
                    scraped.price > 0
                    and scraped.price >= price_floor
                    and scraped.price <= normal_range[1] * 1.3
                )
                
                # Check title for bad words at first pass (fast — no HTTP request needed)
                title_has_bad_word = any(bw in title_lower for bw in all_bad_words)
                
                if not kw_match or not price_ok or title_has_bad_word:
                    filter_reason = (
                        "no_keyword" if not kw_match
                        else "bad_word_title" if title_has_bad_word
                        else "price_out_of_range"
                    )
                    logger.debug(
                        "Filtered [{}] '{}' @ {} UAH (floor={:.0f}, max={:.0f})",
                        filter_reason, scraped.title, scraped.price,
                        price_floor, normal_range[1] * 1.3
                    )
                    with db_session() as session:
                        ad = Ad(
                            olx_id=scraped.olx_id,
                            title=scraped.title,
                            price=scraped.price,
                            url=scraped.url,
                            location=scraped.location,
                            category=category,
                            watch_item_id=watch_item_id,
                            status="filtered"
                        )
                        AdRepository.add(session, ad)
                    continue
                    
                # 5. Fetch details for high potential candidates
                logger.info("Candidate found: '{}' ({} UAH). Fetching details...", scraped.title, scraped.price)
                details_html = await fetch_page(scraped.url)
                if not details_html:
                    continue
                    
                details = parse_details_page(details_html, scraped.url, fallback_title=scraped.title)
                
                # Duplicate check: Description similarity match (>85%) against last 30 ads
                is_desc_duplicate = False
                with db_session() as session:
                    recent_ads = (
                        session.query(Ad)
                        .filter(Ad.watch_item_id == watch_item_id)
                        .order_by(Ad.created_at.desc())
                        .limit(30)
                        .all()
                    )
                    for old_ad in recent_ads:
                        if old_ad.description and get_similarity_ratio(details.description, old_ad.description) >= 0.85:
                            is_desc_duplicate = True
                            break
                            
                    if is_desc_duplicate:
                        ad = Ad(
                            olx_id=scraped.olx_id,
                            title=details.title,
                            price=scraped.price,
                            url=scraped.url,
                            location=details.location or scraped.location,
                            description=details.description,
                            category=category,
                            watch_item_id=watch_item_id,
                            status="filtered_duplicate"
                        )
                        AdRepository.add(session, ad)
                        logger.debug("Filtered duplicate ad by description: '{}'", details.title)
                        continue
                
                # 6. Perform Google Gemini AI audit
                ai_result = await analyze_listing_with_ai(details.title, details.description)
                
                # 7. Run scoring evaluations
                with db_session() as session:
                    recent_prices = MarketSnapshotRepository.get_recent_prices(session, watch_item_id)
                    market_stats = estimate_market_price(scraped.price, item, recent_prices)
                    market_median = market_stats["market_median"]
                    
                    deal_score, expected_profit = calculate_deal_score(
                        price=scraped.price,
                        market_median=market_median,
                        watch_item=item,
                        title=details.title,
                        description=details.description,
                        image_url=details.image_url,
                        published_at=details.published_at,
                        ai_condition_score=ai_result["condition_score"]
                    )
                    
                    risk_score = calculate_risk_score(
                        price=scraped.price,
                        market_median=market_median,
                        title=details.title,
                        description=details.description,
                        image_url=details.image_url,
                        watch_item=item,
                        ai_defects=ai_result["defects"]
                    )
                    
                    # Use AI-corrected product name if available
                    corrected_title = ai_result.get("product_name_corrected") or details.title
                    if corrected_title != details.title:
                        logger.info(
                            "AI corrected product name: '{}' → '{}'",
                            details.title, corrected_title
                        )

                    # Format rich description by embedding the AI Verdict
                    rich_description = details.description or ""
                    if ai_result.get("verdict"):
                        rich_description += f"\n\n🤖 <b>[ИИ Вердикт]:</b> {ai_result['verdict']}"
                        if ai_result.get("defects"):
                            rich_description += f"\n⚠️ <b>Выявленные дефекты:</b> {', '.join(ai_result['defects'])}"
                            
                    ad = Ad(
                        olx_id=scraped.olx_id,
                        title=corrected_title,
                        price=scraped.price,
                        url=scraped.url,
                        location=details.location or scraped.location,
                        description=rich_description,
                        image_url=details.image_url,
                        category=category,
                        watch_item_id=watch_item_id,
                        published_at=details.published_at,
                        deal_score=deal_score,
                        risk_score=risk_score,
                        estimated_market_price=market_median,
                        estimated_profit=expected_profit,
                        status="new"
                    )
                    ad = AdRepository.add(session, ad)
                    
                    # Check learning threshold modifiers
                    mod = get_deal_threshold_modifier(watch_item_id)
                    effective_threshold = settings.deal_score_threshold + mod
                    
                    is_qualified = (
                        deal_score >= effective_threshold and
                        risk_score <= settings.risk_score_max and
                        expected_profit >= min_profit_threshold
                    )
                    
                    if not is_qualified:
                        ad.status = "filtered"
                        logger.debug("Qualified criteria failed for {}. Deal: {} (need {}), Risk: {} (need <= {}), Profit: {} (need >= {})",
                                     ad.olx_id, deal_score, effective_threshold, risk_score, settings.risk_score_max, expected_profit, min_profit_threshold)
                        continue
                        
                    # Check anti-spam: max 3 notifications per cycle
                    if sent_count_this_cycle >= 3:
                        ad.status = "filtered_limit"
                        logger.info("Cycle limit reached (3). Postponing ad: {}", ad.olx_id)
                        continue
                        
                    # Check cooldown: 30 minutes
                    cooldown_list = AdRepository.get_cooldown_ads(session, watch_item_id, minutes=30)
                    has_cooldown = len(cooldown_list) > 0
                    
                    # Super deal exception
                    is_super_deal = (
                        scraped.price <= market_median * 0.6 and
                        risk_score <= 35
                    )
                    
                    should_send = False
                    if not has_cooldown:
                        should_send = True
                    elif is_super_deal:
                        logger.info("Ad {} is a SUPER-DEAL! Bypassing 30m cooldown.", ad.olx_id)
                        should_send = True
                    else:
                        logger.info("Ad {} matches thresholds but cooldown is active.", ad.olx_id)
                        ad.status = "filtered_cooldown"
                        
                    if should_send:
                        # 8. Send Telegram message
                        success = await send_ad_notification(bot, settings.telegram_chat_id, ad, item)
                        if success:
                            ad.sent_to_telegram = True
                            ad.status = "sent"
                            sent_count_this_cycle += 1
                            CategoryStatsRepository.increment_stats(session, category, sent=1)
                            logger.info("Notification sent for {} (id: {})", ad.title, ad.olx_id)
                        else:
                            ad.status = "failed_send"
                            
            except Exception as e:
                logger.error("Exception checking scraped ad: {}", e)
                
    logger.info("Monitoring cycle completed. Sent {} notifications.", sent_count_this_cycle)
