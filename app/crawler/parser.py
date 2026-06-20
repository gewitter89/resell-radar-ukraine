"""
Playwright-based OLX parser — fetches listings + ad details
with anti-detection via OLXBrowser.
"""
import asyncio
import re
import random
import logging
from typing import Optional
from bs4 import BeautifulSoup

from app.crawler.browser import OLXBrowser

logger = logging.getLogger(__name__)


async def fetch_listings(
    browser: OLXBrowser,
    category_url: str,
    max_price: float,
    max_scrolls: int = 5,
) -> list[dict]:
    page = await browser.new_page()
    items = []
    try:
        ok = await browser.goto(page, category_url)
        if not ok:
            logger.error("Failed to load category: %s", category_url)
            return items

        for _ in range(max_scrolls):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(random.uniform(1.5, 3.0))

        content = await page.content()
        soup = BeautifulSoup(content, "lxml")

        cards = soup.select("div[data-cy='l-card']")
        if not cards:
            cards = soup.select("div[data-testid='listing-grid'] > div")

        logger.info("Found %d cards in category", len(cards))

        for card in cards:
            try:
                price_el = card.select_one(
                    "p[data-testid='ad-price'], h3[data-testid='ad-price']"
                )
                if not price_el:
                    continue
                price_text = price_el.text.strip()
                price = int(re.sub(r"\D", "", price_text))
                if price > max_price or price <= 0:
                    continue

                link_el = card.select_one("a[href*='/d/']")
                if not link_el:
                    continue
                href = link_el.get("href", "").split("#")[0]
                if href.startswith("/"):
                    href = "https://www.olx.ua" + href

                title_el = card.select_one("h4, h5, h6")
                title = title_el.text.strip() if title_el else ""

                items.append({"url": href, "price": price, "title": title})
            except Exception as e:
                logger.warning("Card parse error: %s", e)
    finally:
        await page.close()

    seen = set()
    unique = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


async def parse_ad(browser: OLXBrowser, url: str) -> Optional[dict]:
    page = await browser.new_page()
    try:
        ok = await browser.goto(page, url)
        if not ok:
            logger.error("Failed to load ad: %s", url)
            return None

        content = await page.content()
        soup = BeautifulSoup(content, "lxml")

        title_el = soup.select_one("h1[data-cy='ad_title']")
        title = title_el.text.strip() if title_el else ""

        price_el = soup.select_one(
            "h3[data-testid='ad-price'], div[data-testid='ad-price-container']"
        )
        price = 0.0
        if price_el:
            price_text = price_el.text.strip()
            price = float(re.sub(r"[^\d.]", "", price_text.replace(",", ".")))

        desc_el = soup.select_one("div[data-cy='ad_description'] div")
        description = desc_el.text.strip() if desc_el else ""

        photos = []
        imgs = await page.query_selector_all("img[data-testid='ad-image']")
        for img in imgs:
            src = await img.get_attribute("src")
            if src:
                photos.append(src.replace("/thumbnail/", "/big/"))

        seller_name = ""
        seller_block = soup.select_one("div[data-cy='seller-info']")
        if seller_block:
            name_el = seller_block.select_one("h4, a span")
            if name_el:
                seller_name = name_el.text.strip()

        return {
            "url": url,
            "title": title,
            "price": price,
            "description": description,
            "photos": photos,
            "seller_name": seller_name,
        }
    except Exception as e:
        logger.error("Parse ad error %s: %s", url, e)
        return None
    finally:
        await page.close()
