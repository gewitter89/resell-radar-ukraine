from datetime import datetime
from app.utils.logger import logger

def calculate_deal_score(
    price: float,
    market_median: float,
    watch_item: dict,
    title: str = "",
    description: str = "",
    image_url: str | None = None,
    published_at: datetime | None = None,
    first_seen_at: datetime | None = None,
    ai_condition_score: int | None = None
) -> tuple[int, float]:
    """
    Computes deal score (0-100) and expected profit.
    - Price below market median by 30%+ : +35
    - Fresh post (published_at <= 10m): +20, (<= 60m): +10
    - Title matches watchlist keywords: +15
    - Description length >= 100 characters: +10
    - Has photo: +10
    - Price is below watchlist max_green_price: +10
    - AI condition audit: >=85 (+10), <60 (-20), <40 (-40)
    """
    score = 0
    
    # 1. Price comparison
    if market_median > 0:
        discount = (market_median - price) / market_median
        if discount >= 0.30:
            score += 35
        elif discount >= 0.20:
            score += 25
        elif discount >= 0.10:
            score += 15
            
    # 2. Freshness of listing
    pub_time = published_at or first_seen_at
    if pub_time:
        delta_secs = (datetime.utcnow() - pub_time).total_seconds()
        delta_mins = max(0.0, delta_secs / 60.0)
        
        if delta_mins <= 10.0:
            score += 20
        elif delta_mins <= 60.0:
            score += 10
    else:
        score += 10

    # 3. Keywords in title
    title_lower = title.lower() if title else ""
    keywords = watch_item.get("keywords", [])
    if any(k.lower() in title_lower for k in keywords):
        score += 15
        
    # 4. Description adequacy
    desc_clean = description.strip() if description else ""
    if len(desc_clean) >= 100:
        score += 10
        
    # 5. Has image
    if image_url:
        score += 10
        
    # 6. Green price threshold
    max_green = watch_item.get("max_green_price", 0)
    if price <= max_green:
        score += 10
        
    # 7. AI Condition Modifier
    if ai_condition_score is not None:
        if ai_condition_score >= 85:
            score += 10
        elif ai_condition_score < 40:
            score -= 40
        elif ai_condition_score < 60:
            score -= 20
        
    deal_score = min(100, max(0, score))
    
    # Expected profit
    estimated_profit = market_median - price
    
    return deal_score, max(0.0, estimated_profit)
