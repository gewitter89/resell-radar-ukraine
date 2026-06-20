"""
Watchlist Health Monitor — автономное обслуживание списка отслеживания.
- Dead item detection (0 находок за 7 дней)
- Auto-suggest отключение мёртвых позиций
- Super-deal категории (где чаще всего успешные сделки)
"""
import json
import os
from datetime import datetime, timedelta
from app.utils.logger import logger

WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "app", "data", "watchlist.json",
)

DEAD_DAYS = 7
DEAD_MIN_SNAPS = 3


def load_watchlist() -> list[dict]:
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_watchlist(data: list[dict]):
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def check_item_health(watch_id: str, session) -> dict:
    """
    Анализирует здоровье одной позиции watchlist.
    Возвращает: статус, рекомендацию, кол-во находок.
    """
    from app.storage.models import Ad, UserFeedback

    total = session.query(Ad).filter(Ad.watch_item_id == watch_id).count()
    recent = session.query(Ad).filter(
        Ad.watch_item_id == watch_id,
        Ad.first_seen_at >= datetime.utcnow() - timedelta(days=DEAD_DAYS),
    ).count()
    sent = session.query(Ad).filter(
        Ad.watch_item_id == watch_id, Ad.sent_to_telegram == True,
    ).count()
    bought = session.query(Ad).join(UserFeedback).filter(
        Ad.watch_item_id == watch_id, UserFeedback.action == "bought",
    ).count()
    trash = session.query(Ad).join(UserFeedback).filter(
        Ad.watch_item_id == watch_id, UserFeedback.action == "trash",
    ).count()

    status = "healthy"
    reason = ""

    if total < DEAD_MIN_SNAPS and total > 0 and recent == 0:
        status = "low_volume"
        reason = "Мало новых объявлений за 7 дней"
    elif recent == 0 and total >= DEAD_MIN_SNAPS:
        status = "dead"
        reason = "Нет новых объявлений за 7 дней"
    elif trash > sent * 0.6 and sent > 3:
        status = "noisy"
        reason = "Более 60% находок — мусор"
    elif bought >= 3:
        status = "golden"
        reason = f"{bought} успешных покупок!"

    return {
        "watch_id": watch_id,
        "status": status,
        "reason": reason,
        "total": total,
        "recent": recent,
        "sent": sent,
        "bought": bought,
        "trash": trash,
    }


def auto_cleanup(session) -> list[dict]:
    """
    Автоматически отмечает мёртвые позиции.
    Возвращает список изменений.
    """
    watchlist = load_watchlist()
    changes = []

    for item in watchlist:
        health = check_item_health(item["id"], session)
        if health["status"] == "dead" and not item.get("_paused"):
            item["_paused"] = True
            item["_paused_at"] = datetime.utcnow().isoformat()
            changes.append({
                "id": item["id"],
                "name": item["name"],
                "action": "auto_paused",
                "reason": health["reason"],
            })
            logger.info("Auto-paused dead item: {} ({})", item["name"], health["reason"])

    if changes:
        save_watchlist(watchlist)

    return changes


def get_top_categories(session) -> list[dict]:
    """
    Возвращает категории, отсортированные по успешности.
    Используется для рекомендаций новых позиций.
    """
    from app.storage.models import Ad, UserFeedback
    from sqlalchemy import func

    cats = session.query(
        Ad.category,
        func.count(Ad.id).label("total"),
        func.sum(
            func.case((UserFeedback.action == "bought", 1), else_=0)
        ).label("bought"),
        func.sum(
            func.case((UserFeedback.action == "trash", 1), else_=0)
        ).label("trash"),
    ).outerjoin(UserFeedback, Ad.id == UserFeedback.ad_id).group_by(Ad.category).all()

    result = []
    for cat in cats:
        total = cat.total or 0
        bought = cat.bought or 0
        trash = cat.trash or 0
        score = (bought * 10) - trash if total > 0 else 0
        if total > 0:
            result.append({
                "category": cat.category,
                "total": total,
                "bought": bought,
                "trash": trash,
                "score": score,
            })

    return sorted(result, key=lambda x: x["score"], reverse=True)
