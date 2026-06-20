import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey, Index, JSON
from app.storage.database import Base


class Ad(Base):
    __tablename__ = "ads"
    __table_args__ = (
        Index("idx_ads_olx_id", "olx_id"),
        Index("idx_ads_watch_item", "watch_item_id"),
        Index("idx_ads_status", "status"),
        Index("idx_ads_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    olx_id = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    url = Column(String, nullable=False)
    location = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)
    category = Column(String, nullable=False)
    watch_item_id = Column(String, nullable=False)
    published_at = Column(DateTime, nullable=True)
    first_seen_at = Column(DateTime, default=datetime.datetime.utcnow)
    deal_score = Column(Integer, default=0)
    risk_score = Column(Integer, default=0)
    estimated_market_price = Column(Float, default=0.0)
    estimated_profit = Column(Float, default=0.0)
    analysis_json = Column(JSON, nullable=True)
    status = Column(String, default="new")
    sent_to_telegram = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class UserFeedback(Base):
    __tablename__ = "user_feedback"
    __table_args__ = (
        Index("idx_feedback_ad", "ad_id"),
        Index("idx_feedback_action", "action"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ad_id = Column(Integer, ForeignKey("ads.id", ondelete="CASCADE"), nullable=False)
    action = Column(String, nullable=False)
    buy_price = Column(Integer, nullable=True)
    sell_price = Column(Integer, nullable=True)
    profit = Column(Integer, nullable=True)
    roi = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        Index("idx_snapshot_watch_item", "watch_item_id"),
        Index("idx_snapshot_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    watch_item_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    url = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class PriceAlert(Base):
    """Tracks price drops for re-alerts."""
    __tablename__ = "price_alerts"
    __table_args__ = (
        Index("idx_alert_url", "url"),
        Index("idx_alert_watch_item", "watch_item_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String, nullable=False)
    watch_item_id = Column(String, nullable=False)
    last_price = Column(Integer, nullable=False)
    lowest_price = Column(Integer, nullable=False)
    alert_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class AiPrediction(Base):
    """Tracks AI predictions vs actual outcomes for self-learning."""
    __tablename__ = "ai_predictions"
    __table_args__ = (
        Index("idx_prediction_ad", "ad_id"),
        Index("idx_prediction_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ad_id = Column(Integer, ForeignKey("ads.id", ondelete="CASCADE"), nullable=False)
    watch_item_id = Column(String, nullable=False)
    
    # What AI predicted
    predicted_condition = Column(String, nullable=True)
    predicted_resell_price = Column(Integer, default=0)
    predicted_profit = Column(Integer, default=0)
    predicted_liquidity = Column(String, nullable=True)
    
    # What actually happened (filled later via feedback)
    actual_action = Column(String, nullable=True)  # bought, sold, trash
    actual_buy_price = Column(Integer, nullable=True)
    actual_sell_price = Column(Integer, nullable=True)
    actual_profit = Column(Integer, nullable=True)
    
    # Accuracy metrics
    price_accuracy_pct = Column(Float, nullable=True)  # how close was prediction
    was_accurate = Column(Boolean, nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class CategoryStats(Base):
    __tablename__ = "category_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String, unique=True, nullable=False)
    total_sent = Column(Integer, default=0)
    total_bought = Column(Integer, default=0)
    total_trash = Column(Integer, default=0)
    total_sold = Column(Integer, default=0)
    total_profit = Column(Integer, default=0)
    avg_roi = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
