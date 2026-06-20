"""
OLXBrowser — Playwright-based anti-detection scraper.
Uses playwright-stealth + fingerprint randomization + proxy rotation.
"""
import asyncio
import random
import logging
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

LOCALES = ["uk-UA", "uk", "en-US", "ru-RU"]
TIMEZONES = ["Europe/Kiev", "Europe/Helsinki"]


class OLXBrowser:
    def __init__(
        self,
        proxy: Optional[str] = None,
        headless: bool = False,
        slow_mo: int = 50,
    ):
        self.proxy = proxy
        self.headless = headless
        self.slow_mo = slow_mo
        self.playwright = None
        self.browser = None
        self.context = None

    async def start(self):
        self.playwright = await async_playwright().start()
        launch_args = {
            "headless": self.headless,
            "slow_mo": self.slow_mo,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        }
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}

        self.browser = await self.playwright.chromium.launch(**launch_args)

        ua = random.choice(USER_AGENTS)
        vp = random.choice(VIEWPORTS)
        locale = random.choice(LOCALES)
        tz = random.choice(TIMEZONES)

        self.context = await self.browser.new_context(
            user_agent=ua,
            viewport=vp,
            locale=locale,
            timezone_id=tz,
            geolocation={"longitude": 30.52, "latitude": 50.45},
            permissions=["geolocation"],
        )

        await self._inject_stealth()
        logger.info("OLXBrowser started. UA: %s, VP: %s", ua[:50], vp)

    async def _inject_stealth(self):
        await self.context.add_init_script("""
            delete Object.getPrototypeOf(navigator).webdriver;
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            window.chrome = { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : originalQuery(parameters)
            );
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Intel Inc.';
                if (parameter === 37446) return 'Intel Iris OpenGL Engine';
                return getParameter.call(this, parameter);
            };
        """)

    async def new_page(self) -> Page:
        page = await self.context.new_page()
        return page

    async def close(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("OLXBrowser stopped.")

    async def simulate_human(self, page: Page):
        await page.evaluate("window.scrollBy(0, Math.random() * 500 + 200)")
        await asyncio.sleep(random.uniform(0.3, 1.2))

    async def goto(
        self, page: Page, url: str, max_retries: int = 3
    ) -> bool:
        for attempt in range(max_retries):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await self.simulate_human(page)
                if not await self._has_captcha(page):
                    return True
                logger.warning(
                    "Captcha detected, attempt %d/%d", attempt + 1, max_retries
                )
                await asyncio.sleep(15)
            except Exception as e:
                logger.warning("Goto error attempt %d: %s", attempt + 1, e)
                await asyncio.sleep(5)
        return False

    async def _has_captcha(self, page: Page) -> bool:
        try:
            return await page.evaluate("""
                document.querySelector('div#challenge-stage') !== null
                || document.querySelector('iframe[title*="captcha"]') !== null
                || document.querySelector('iframe[src*="challenge"]') !== null
            """)
        except Exception:
            return False
