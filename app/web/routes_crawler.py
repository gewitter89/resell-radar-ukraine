"""
Crawler API routes — test Playwright scraper via HTTP.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.crawler.browser import OLXBrowser
from app.crawler.parser import fetch_listings, parse_ad
from app.services.engine import run_full_cycle
from app.celery_app import celery

router = APIRouter(prefix="/crawler", tags=["crawler"])


class CrawlRequest(BaseModel):
    url: str = "https://www.olx.ua/uk/elektronika/telefony-i-aksesuary/"
    max_price: float = 10000
    proxy: str | None = None


@router.post("/test-browser")
async def test_browser(req: CrawlRequest):
    """Test Playwright: open page and return title."""
    browser = OLXBrowser(proxy=req.proxy, headless=False)
    try:
        await browser.start()
        page = await browser.new_page()
        ok = await browser.goto(page, req.url)
        title = await page.title() if ok else "failed"
        await browser.close()
        return {"title": title, "status": "ok" if ok else "captcha"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fetch-listings")
async def api_fetch_listings(req: CrawlRequest):
    """Fetch listings via Playwright."""
    browser = OLXBrowser(proxy=req.proxy, headless=True)
    try:
        await browser.start()
        items = await fetch_listings(browser, req.url, req.max_price)
        await browser.close()
        return {"count": len(items), "listings": items[:20]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ParseRequest(BaseModel):
    url: str
    proxy: str | None = None


@router.post("/parse-ad")
async def api_parse_ad(req: ParseRequest):
    """Parse a single ad via Playwright."""
    browser = OLXBrowser(proxy=req.proxy, headless=True)
    try:
        await browser.start()
        ad = await parse_ad(browser, req.url)
        await browser.close()
        if not ad:
            raise HTTPException(status_code=404, detail="Parse failed")
        return {"ad": ad}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run-cycle")
async def api_run_cycle():
    """Run full monitoring cycle (blocking, may take minutes)."""
    import asyncio
    try:
        await run_full_cycle()
        return {"status": "ok", "message": "Full cycle completed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dispatch-cycle")
async def api_dispatch_cycle():
    """Dispatch Celery task for full cycle."""
    from app.celery_tasks.scraper_tasks import crawl_all_watchlist
    task = crawl_all_watchlist.delay()
    return {"task_id": task.id, "status": "dispatched"}
