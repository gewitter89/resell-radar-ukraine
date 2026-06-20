from celery import Celery
from config import settings

celery = Celery(
    "resell_radar",
    broker=settings.effective_broker_url,
    backend=settings.effective_broker_url,
    include=["app.celery_tasks"],
)

# Beat schedule — auto-crawl watchlist every 10 minutes
celery.conf.beat_schedule = {
    "crawl-all-watchlist": {
        "task": "app.celery_tasks.scraper_tasks.crawl_all_watchlist",
        "schedule": 600.0,
    },
}

celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=300,
    task_time_limit=600,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=86400,
    worker_max_tasks_per_child=1000,
    timezone="Europe/Kiev",
    enable_utc=True,
)
