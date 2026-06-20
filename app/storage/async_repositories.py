"""Async repositories — used by Celery tasks and new async code."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
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


class AsyncAdRepository:
    @staticmethod
    async def get_by_olx_id(session: AsyncSession, olx_id: str) -> Ad | None:
        result = await session.execute(select(Ad).where(Ad.olx_id == olx_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, ad_id: int) -> Ad | None:
        result = await session.execute(select(Ad).where(Ad.id == ad_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def add(session: AsyncSession, ad: Ad) -> Ad:
        session.add(ad)
        await session.flush()
        return ad

    @staticmethod
    async def get_cooldown_ads(session: AsyncSession, watch_item_id: str, minutes: int = 30) -> list[Ad]:
        since = datetime.utcnow() - timedelta(minutes=minutes)
        result = await session.execute(
            select(Ad).where(
                Ad.watch_item_id == watch_item_id,
                Ad.sent_to_telegram == True,
                Ad.first_seen_at >= since,
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_total_found_count(session: AsyncSession) -> int:
        result = await session.execute(select(func.count(Ad.id)))
        return result.scalar() or 0

    @staticmethod
    async def get_total_sent_count(session: AsyncSession) -> int:
        result = await session.execute(
            select(func.count(Ad.id)).where(Ad.sent_to_telegram == True)
        )
        return result.scalar() or 0

    @staticmethod
    async def get_recent_by_watch_item(session: AsyncSession, watch_item_id: str, limit: int = 30) -> list[Ad]:
        result = await session.execute(
            select(Ad)
            .where(Ad.watch_item_id == watch_item_id)
            .order_by(desc(Ad.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())


class AsyncFeedbackRepository:
    @staticmethod
    async def add(session: AsyncSession, feedback: UserFeedback) -> UserFeedback:
        session.add(feedback)
        await session.flush()
        return feedback

    @staticmethod
    async def get_action_count(session: AsyncSession, action: str) -> int:
        result = await session.execute(
            select(func.count(UserFeedback.id)).where(UserFeedback.action == action)
        )
        return result.scalar() or 0

    @staticmethod
    async def get_financial_summary(session: AsyncSession) -> dict:
        result = await session.execute(
            select(func.sum(UserFeedback.profit)).where(UserFeedback.action == "sold")
        )
        total_profit = result.scalar() or 0

        roi_result = await session.execute(
            select(UserFeedback.roi).where(
                UserFeedback.action == "sold", UserFeedback.roi.isnot(None)
            )
        )
        rois = [r[0] for r in roi_result.all() if r[0] is not None]
        avg_roi = sum(rois) / len(rois) if rois else 0.0

        best_category = await session.execute(
            select(Ad.category, func.sum(UserFeedback.profit).label("tot_profit"))
            .join(UserFeedback, Ad.id == UserFeedback.ad_id)
            .where(UserFeedback.action == "sold")
            .group_by(Ad.category)
            .order_by(desc("tot_profit"))
            .limit(1)
        )
        best_cat_row = best_category.first()

        best_item = await session.execute(
            select(Ad.watch_item_id, func.sum(UserFeedback.profit).label("tot_profit"))
            .join(UserFeedback, Ad.id == UserFeedback.ad_id)
            .where(UserFeedback.action == "sold")
            .group_by(Ad.watch_item_id)
            .order_by(desc("tot_profit"))
            .limit(1)
        )
        best_item_row = best_item.first()

        return {
            "total_profit": int(total_profit),
            "avg_roi": round(float(avg_roi), 2),
            "best_category": best_cat_row[0] if best_cat_row else "N/A",
            "best_item": best_item_row[0] if best_item_row else "N/A",
        }


class AsyncMarketSnapshotRepository:
    @staticmethod
    async def add(session: AsyncSession, snapshot: MarketSnapshot) -> MarketSnapshot:
        session.add(snapshot)
        await session.flush()
        return snapshot

    @staticmethod
    async def get_recent_prices(session: AsyncSession, watch_item_id: str, limit: int = 50) -> list[int]:
        result = await session.execute(
            select(MarketSnapshot)
            .where(MarketSnapshot.watch_item_id == watch_item_id)
            .order_by(desc(MarketSnapshot.created_at))
            .limit(limit)
        )
        return [s.price for s in result.scalars().all() if s.price > 0]


class AsyncCategoryStatsRepository:
    @staticmethod
    async def get_by_category(session: AsyncSession, category: str) -> CategoryStats | None:
        result = await session.execute(
            select(CategoryStats).where(CategoryStats.category == category)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(session: AsyncSession, category: str) -> CategoryStats:
        stats = await AsyncCategoryStatsRepository.get_by_category(session, category)
        if not stats:
            stats = CategoryStats(category=category)
            session.add(stats)
            await session.flush()
        return stats

    @staticmethod
    async def increment_stats(
        session: AsyncSession, category: str,
        sent: int = 0, bought: int = 0, trash: int = 0, sold: int = 0, profit: int = 0,
    ) -> CategoryStats:
        stats = await AsyncCategoryStatsRepository.get_or_create(session, category)
        stats.total_sent += sent
        stats.total_bought += bought
        stats.total_trash += trash
        stats.total_sold += sold
        stats.total_profit += profit
        roi_result = await session.execute(
            select(UserFeedback.roi)
            .join(Ad, Ad.id == UserFeedback.ad_id)
            .where(Ad.category == category, UserFeedback.action == "sold", UserFeedback.roi.isnot(None))
        )
        sold_feedbacks = [r[0] for r in roi_result.all() if r[0] is not None]
        stats.avg_roi = sum(sold_feedbacks) / len(sold_feedbacks) if sold_feedbacks else 0.0
        stats.updated_at = datetime.utcnow()
        await session.flush()
        return stats

    @staticmethod
    async def get_all_ordered_by_profit(session: AsyncSession) -> list[CategoryStats]:
        result = await session.execute(
            select(CategoryStats).order_by(desc(CategoryStats.total_profit))
        )
        return list(result.scalars().all())
