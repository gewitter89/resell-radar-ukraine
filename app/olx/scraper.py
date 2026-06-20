import asyncio
import random
import httpx
from app.utils.logger import logger
from app.utils.proxies import get_next_proxy

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

def get_random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7,ru;q=0.6",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1"
    }

async def fetch_page(url: str, retries: int = 2) -> str | None:
    """
    Fetches raw HTML from a URL with retry logic, random delay, and proxy rotation.
    """
    # Sleep to simulate human behavior (1-3 seconds)
    delay = random.uniform(1.0, 3.0)
    await asyncio.sleep(delay)
    
    for attempt in range(retries + 1):
        headers = get_random_headers()
        proxy = get_next_proxy()
        
        if proxy:
            logger.debug("Routing request via proxy: {}", proxy)
            
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, 
                timeout=12.0,
                proxy=proxy
            ) as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    return response.text
                elif response.status_code in [403, 429]:
                    logger.warning("Scraper rate-limited or blocked (status {}). Proxy: {}, URL: {}", 
                                   response.status_code, proxy or "Local IP", url)
                else:
                    logger.warning("Scraper returned non-200 status ({}). Proxy: {}, URL: {}", 
                                   response.status_code, proxy or "Local IP", url)
                    
        except httpx.RequestError as e:
            logger.warning("Request error on attempt {} via proxy {}: {}", attempt + 1, proxy or "Local IP", e)
            
        if attempt < retries:
            # Exponential backoff
            wait_time = 2.0 ** (attempt + 1) + random.uniform(0.5, 1.5)
            logger.info("Waiting {}s before retry...", wait_time)
            await asyncio.sleep(wait_time)
            
    logger.error("Failed to fetch URL after {} attempts: {}", retries + 1, url)
    return None

