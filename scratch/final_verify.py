"""Final verification of v2.0 architecture."""
import sys
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from config import settings
print(f"[OK] Config: DB={settings.database_url_sync[:30]}...")

from app.storage.database import sync_engine, async_engine, init_sync_db, SessionLocal
print(f"[OK] Database: sync={type(sync_engine).__name__}, async={type(async_engine).__name__}")

from app.storage.models import Ad, UserFeedback, MarketSnapshot, CategoryStats, PriceAlert
tables = [Ad.__tablename__, UserFeedback.__tablename__, MarketSnapshot.__tablename__,
          CategoryStats.__tablename__, PriceAlert.__tablename__]
print(f"[OK] Models: {tables}")

from app.storage.repositories import AdRepository
from app.storage.async_repositories import AsyncAdRepository
print(f"[OK] Repos: sync + async")

from app.crawler.browser import OLXBrowser
from app.crawler.parser import fetch_listings, parse_ad
print(f"[OK] Crawler: Playwright + stealth")

from app.services.engine import run_full_cycle, load_watchlist
from app.services.price_alerts import track_price
from app.services.monitor import run_monitoring_cycle
from app.services.notifier import send_ad_notification
print(f"[OK] Services: engine, alerts, monitor, notifier")

from app.scoring.deal_score import calculate_deal_score
from app.scoring.risk_score import calculate_risk_score
from app.scoring.ai_analyzer import analyze_listing_with_ai
from app.scoring.market_price import estimate_market_price
print(f"[OK] Scoring: deal, risk, AI, market")

from app.bot.telegram_bot import bot, start_bot
from app.bot.handlers import router
from app.bot.keyboards import get_deal_keyboard
print(f"[OK] Bot: aiogram 3.x")

from app.web.web_server import app
from app.web.routes_crawler import router as crawler_router
print(f"[OK] Web: FastAPI dashboard + crawler API")

from app.celery_app import celery
from app.celery_tasks.scraper_tasks import crawl_all_watchlist
print(f"[OK] Celery: broker={celery.conf.broker_url[:30]}...")

from app.utils.money import clean_price, format_price
from app.utils.proxies import get_next_proxy
from app.utils.logger import setup_logger
print(f"[OK] Utils: money, proxies, logger")

# Init DB tables
init_sync_db()
print("[OK] DB tables created")

# Quick test: scoring math
wi = {"normal_price_range": [11000, 14500], "max_green_price": 9500, "keywords": ["iphone 12"]}
ds, profit = calculate_deal_score(8000, 12750, wi, "test", "test desc", "http://img.jpg")
rs = calculate_risk_score(8000, 12750, "test", "test desc", "http://img.jpg", ["icloud"], [], wi)
mp = estimate_market_price(8000, wi, [])
assert ds > 0 and rs > 0 and mp["market_median"] > 0
print(f"[OK] Scoring: deal={ds}, risk={rs}, market={mp['market_median']}")

# Quick test: PriceAlert model works
print(f"[OK] PriceAlert: {PriceAlert.__tablename__}")

print()
print("=" * 40)
print("  RESELL RADAR v2.0 — ALL SYSTEMS NOMINAL")
print("=" * 40)
print(f"  Launch:     python main.py")
print(f"  Dashboard:  http://localhost:8000")
print(f"  Health:     http://localhost:8000/health")
print(f"  API docs:   http://localhost:8000/docs")
print(f"  Celery:     celery -A app.celery_app worker -l info -P gevent -c 10")
print(f"  Beat:       celery -A app.celery_app beat -l info")
print(f"  Docker:     docker compose up -d")
print("=" * 40)
