"""
Celery tasks for OLX scraping.
Run worker:  celery -A app.celery_app worker -l info -P gevent -c 10
Run beat:    celery -A app.celery_app beat -l info
"""
import asyncio
from celery import shared_task
from app.services.engine import run_full_cycle
from app.utils.logger import logger


@shared_task
def crawl_all_watchlist():
    """Full cycle: Playwright → parse → AI → score → notify."""
    logger.info("Celery task: crawl_all_watchlist started")
    asyncio.run(run_full_cycle())
    logger.info("Celery task: crawl_all_watchlist done")
