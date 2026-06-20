"""Sync repositories — used by bot handlers and web server."""
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta
from app.storage.models import Ad, UserFeedback, MarketSnapshot, CategoryStats


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_v[mid - 1] + sorted_v[mid]) / 2.0
    return float(sorted_v[mid])


class AdRepository:
    @staticmethod
    def get_by_olx_id(session: Session, olx_id: str) -> Ad | None:
        return session.query(Ad).filter(Ad.olx_id == olx_id).first()

    @staticmethod
    def get_by_id(session: Session, ad_id: int) -> Ad | None:
        return session.query(Ad).filter(Ad.id == ad_id).first()

    @staticmethod
    def add(session: Session, ad: Ad) -> Ad:
        session.add(ad)
        session.flush()
        return ad

    @staticmethod
    def get_cooldown_ads(session: Session, watch_item_id: str, minutes: int = 30) -> list[Ad]:
        since = datetime.utcnow() - timedelta(minutes=minutes)
        return (
            session.query(Ad)
            .filter(
                Ad.watch_item_id == watch_item_id,
                Ad.sent_to_telegram == True,
                Ad.first_seen_at >= since,
            )
            .all()
        )

    @staticmethod
    def get_total_found_count(session: Session) -> int:
        return session.query(func.count(Ad.id)).scalar() or 0

    @staticmethod
    def get_total_sent_count(session: Session) -> int:
        return session.query(func.count(Ad.id)).filter(Ad.sent_to_telegram == True).scalar() or 0

    @staticmethod
    def get_recent_by_watch_item(session: Session, watch_item_id: str, limit: int = 30) -> list[Ad]:
        return (
            session.query(Ad)
            .filter(Ad.watch_item_id == watch_item_id)
            .order_by(desc(Ad.created_at))
            .limit(limit)
            .all()
        )


class FeedbackRepository:
    @staticmethod
    def add(session: Session, feedback: UserFeedback) -> UserFeedback:
        session.add(feedback)
        session.flush()
        return feedback

    @staticmethod
    def get_action_count(session: Session, action: str) -> int:
        return session.query(func.count(UserFeedback.id)).filter(UserFeedback.action == action).scalar() or 0

    @staticmethod
    def get_financial_summary(session: Session) -> dict:
        total_profit = session.query(func.sum(UserFeedback.profit)).filter(UserFeedback.action == "sold").scalar() or 0
        rois = session.query(UserFeedback.roi).filter(
            UserFeedback.action == "sold", UserFeedback.roi.isnot(None)
        ).all()
        avg_roi = sum(r[0] for r in rois) / len(rois) if rois else 0.0

        best_category = (
            session.query(Ad.category, func.sum(UserFeedback.profit).label("tot_profit"))
            .join(UserFeedback, Ad.id == UserFeedback.ad_id)
            .filter(UserFeedback.action == "sold")
            .group_by(Ad.category)
            .order_by(desc("tot_profit"))
            .first()
        )
        best_item = (
            session.query(Ad.watch_item_id, func.sum(UserFeedback.profit).label("tot_profit"))
            .join(UserFeedback, Ad.id == UserFeedback.ad_id)
            .filter(UserFeedback.action == "sold")
            .group_by(Ad.watch_item_id)
            .order_by(desc("tot_profit"))
            .first()
        )
        return {
            "total_profit": int(total_profit),
            "avg_roi": round(float(avg_roi), 2),
            "best_category": best_category[0] if best_category else "N/A",
            "best_item": best_item[0] if best_item else "N/A",
        }


class MarketSnapshotRepository:
    @staticmethod
    def add(session: Session, snapshot: MarketSnapshot) -> MarketSnapshot:
        session.add(snapshot)
        session.flush()
        return snapshot

    @staticmethod
    def get_recent_prices(session: Session, watch_item_id: str, limit: int = 50) -> list[int]:
        snapshots = (
            session.query(MarketSnapshot)
            .filter(MarketSnapshot.watch_item_id == watch_item_id)
            .order_by(desc(MarketSnapshot.created_at))
            .limit(limit)
            .all()
        )
        return [s.price for s in snapshots if s.price > 0]


class CategoryStatsRepository:
    @staticmethod
    def get_by_category(session: Session, category: str) -> CategoryStats | None:
        return session.query(CategoryStats).filter(CategoryStats.category == category).first()

    @staticmethod
    def get_or_create(session: Session, category: str) -> CategoryStats:
        stats = CategoryStatsRepository.get_by_category(session, category)
        if not stats:
            stats = CategoryStats(category=category)
            session.add(stats)
            session.flush()
        return stats

    @staticmethod
    def increment_stats(session: Session, category: str, sent: int = 0, bought: int = 0, trash: int = 0, sold: int = 0, profit: int = 0) -> CategoryStats:
        stats = CategoryStatsRepository.get_or_create(session, category)
        stats.total_sent += sent
        stats.total_bought += bought
        stats.total_trash += trash
        stats.total_sold += sold
        stats.total_profit += profit
        sold_feedbacks = (
            session.query(UserFeedback.roi)
            .join(Ad, Ad.id == UserFeedback.ad_id)
            .filter(Ad.category == category, UserFeedback.action == "sold", UserFeedback.roi.isnot(None))
            .all()
        )
        stats.avg_roi = sum(f[0] for f in sold_feedbacks) / len(sold_feedbacks) if sold_feedbacks else 0.0
        stats.updated_at = datetime.utcnow()
        session.flush()
        return stats

    @staticmethod
    def get_all_ordered_by_profit(session: Session) -> list[CategoryStats]:
        return session.query(CategoryStats).order_by(desc(CategoryStats.total_profit)).all()
