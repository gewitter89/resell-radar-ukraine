"""
Price-drop re-alert service.
Tracks watched listings and re-notifies when price drops significantly.
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.storage.models import PriceAlert
from app.utils.logger import logger

RE_ALERT_THRESHOLD = 0.85  # Send re-alert if price drops to 85% or less of last alert


def track_price(session: Session, url: str, watch_item_id: str, current_price: int) -> bool:
    """
    Track a listing's price.
    Returns True if a re-alert should be sent.
    """
    alert = session.query(PriceAlert).filter(PriceAlert.url == url).first()

    if not alert:
        alert = PriceAlert(
            url=url,
            watch_item_id=watch_item_id,
            last_price=current_price,
            lowest_price=current_price,
        )
        session.add(alert)
        session.flush()
        return False

    alert.last_price = current_price
    if current_price < alert.lowest_price:
        alert.lowest_price = current_price

    if alert.lowest_price < alert.last_price * RE_ALERT_THRESHOLD:
        # Price dropped significantly since last alert
        if not alert.alert_sent_at or (datetime.utcnow() - alert.alert_sent_at) > timedelta(hours=6):
            alert.alert_sent_at = datetime.utcnow()
            alert.last_price = current_price
            session.flush()
            logger.info("Price drop re-alert triggered for %s: %d UAH", url, current_price)
            return True

    return False
