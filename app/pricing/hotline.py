"""
Hotline.ua price scraper — real Ukrainian retail prices.
Used as market price reference for AI analysis.
"""
import re
import httpx
from bs4 import BeautifulSoup
from app.utils.logger import logger


async def get_hotline_price(product_name: str) -> dict | None:
    """
    Search Hotline.ua for product and return price stats.
    Returns: {"min": int, "avg": int, "max": int, "count": int} or None.
    """
    try:
        query = product_name.replace(" ", "+")
        url = f"https://hotline.ua/sr/?q={query}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8",
        }

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.content, "lxml")
        prices = []

        for item in soup.select("[class*='price'], span[class*='cost']"):
            text = item.text.strip()
            digits = re.sub(r"[^\d]", "", text)
            if digits and 100 <= int(digits) <= 500000:
                prices.append(int(digits))

        if not prices:
            return None

        prices.sort()
        n = len(prices)
        mid = n // 2
        median = prices[mid] if n % 2 else (prices[mid - 1] + prices[mid]) // 2

        return {
            "min": prices[0],
            "max": prices[-1],
            "avg": sum(prices) // n,
            "median": median,
            "count": n,
        }
    except Exception as e:
        logger.debug("Hotline price fetch failed: %s", e)
        return None
