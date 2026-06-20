"""
AI self-learning system.
Tracks predictions, measures accuracy, adjusts thresholds based on results.
"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.storage.models import AiPrediction
from app.utils.logger import logger


def record_prediction(session: Session, ad_id: int, watch_item_id: str, analysis: dict):
    """Save AI prediction when a deal is sent to user."""
    pred = AiPrediction(
        ad_id=ad_id,
        watch_item_id=watch_item_id,
        predicted_condition=analysis.get("condition_type", ""),
        predicted_resell_price=int(analysis.get("estimated_resell_price", 0)),
        predicted_profit=int(analysis.get("expected_profit", 0)),
        predicted_liquidity=analysis.get("liquidity", ""),
    )
    session.add(pred)
    session.flush()
    return pred.id


def record_outcome(session: Session, ad_id: int, action: str, buy_price: int = 0, sell_price: int = 0):
    """Fill actual outcome when user clicks Купил/Продал."""
    preds = session.query(AiPrediction).filter(
        AiPrediction.ad_id == ad_id,
        AiPrediction.actual_action.is_(None),
    ).all()

    for pred in preds:
        pred.actual_action = action
        if buy_price:
            pred.actual_buy_price = buy_price
        if sell_price:
            pred.actual_sell_price = sell_price
            pred.actual_profit = sell_price - (buy_price or 0)

        # Calculate accuracy
        if pred.predicted_resell_price and sell_price:
            diff = abs(pred.predicted_resell_price - sell_price)
            max_price = max(pred.predicted_resell_price, sell_price)
            pred.price_accuracy_pct = max(0, (1 - diff / max_price)) * 100 if max_price else 0
            pred.was_accurate = pred.price_accuracy_pct >= 70

            logger.info(
                "AI accuracy: predicted=%d, actual=%d, accuracy=%.1f%%",
                pred.predicted_resell_price, sell_price, pred.price_accuracy_pct,
            )

    session.flush()


def get_accuracy_stats(session: Session) -> dict:
    """Get overall AI accuracy statistics."""
    total = session.query(AiPrediction).count()
    accurate = session.query(AiPrediction).filter(
        AiPrediction.was_accurate == True,
    ).count()
    with_outcome = session.query(AiPrediction).filter(
        AiPrediction.actual_action.isnot(None),
    ).count()

    avg_accuracy = 0.0
    if with_outcome:
        result = session.query(
            session.query(AiPrediction).filter(
                AiPrediction.price_accuracy_pct.isnot(None)
            ).statement
        ).with_only_columns(
            session.query(AiPrediction.price_accuracy_pct).filter(
                AiPrediction.price_accuracy_pct.isnot(None)
            ).statement
        ).all()
        vals = [r[0] for r in result if r[0] is not None]
        avg_accuracy = sum(vals) / len(vals) if vals else 0

    return {
        "total_predictions": total,
        "with_outcome": with_outcome,
        "accurate": accurate,
        "accuracy_rate": round(accurate / with_outcome * 100, 1) if with_outcome else 0,
        "avg_price_accuracy": round(avg_accuracy, 1),
    }


def get_accuracy_by_category(session: Session) -> list[dict]:
    """Get accuracy stats broken down by watchlist item."""
    from app.storage.models import Ad
    results = session.query(
        AiPrediction.watch_item_id,
        AiPrediction.predicted_liquidity,
        AiPrediction.was_accurate,
    ).all()

    stats = {}
    for r in results:
        wid = r.watch_item_id
        if wid not in stats:
            stats[wid] = {"total": 0, "accurate": 0, "total_profit": 0}
        stats[wid]["total"] += 1
        if r.was_accurate:
            stats[wid]["accurate"] += 1

    return [
        {
            "watch_item_id": wid,
            "total": s["total"],
            "accuracy": round(s["accurate"] / s["total"] * 100, 1) if s["total"] else 0,
        }
        for wid, s in sorted(stats.items(), key=lambda x: x[1]["total"], reverse=True)
    ]


def get_adjusted_threshold(watch_item_id: str, base_threshold: int, session: Session) -> int:
    """Adjust threshold based on AI accuracy for this item."""
    stats = get_accuracy_stats(session)
    if stats["accuracy_rate"] >= 80:
        return base_threshold - 5  # AI is reliable, be more aggressive
    elif stats["accuracy_rate"] <= 40 and stats["with_outcome"] >= 5:
        return base_threshold + 5  # AI is unreliable, be more conservative
    return base_threshold
