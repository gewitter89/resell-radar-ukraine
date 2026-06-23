"""
JS Scraper — Playwright обёртка для магазинов с Cloudflare.

Использование:
  from js_fetch import fetch_js
  html = await fetch_js("https://zakaz.ua/uk/search/?q=молоко")

Требования:
  playwright>=1.47.0 (уже есть в requirements.txt)
  python -m playwright install chromium   (одноразово)
"""

import asyncio
from typing import Optional


async def fetch_js(url: str, timeout: int = 15000, headless: bool = True) -> Optional[str]:
    """
    Загружает страницу через Playwright (JS-рендеринг).
    Обходит Cloudflare и другие JS-защиты.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None  # Playwright не установлен → fallback на httpx

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="uk-UA",
            )
            page = await context.new_page()

            await page.goto(url, wait_until="domcontentloaded", timeout=float(timeout))
            await page.wait_for_timeout(2000)  # ждём рендер цен

            html = await page.content()
            await browser.close()
            return html

    except Exception:
        return None


async def fetch_with_fallback(url: str, timeout: int = 15) -> Optional[str]:
    """
    Сначала пробует httpx (быстро), при 403/пустом ответе — Playwright.
    """
    import httpx

    # Быстрая попытка через httpx
    try:
        async with httpx.AsyncClient(
            timeout=float(timeout),
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 Chrome/124.0.0.0",
                    "Accept-Language": "uk-UA,uk;q=0.9",
                },
            )
            if resp.status_code == 200 and len(resp.text) > 500:
                return resp.text
    except Exception:
        pass

    # Fallback: Playwright
    return await fetch_js(url, timeout=timeout * 1000)
