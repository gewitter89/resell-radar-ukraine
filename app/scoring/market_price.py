def estimate_market_price(price: float, watch_item: dict, recent_prices: list[int]) -> dict:
    """
    Estimates market price parameters.
    - If recent_prices has >= 10 items, removes outliers (outer 15%) and calculates stats.
    - Otherwise, falls back to the normal_price_range defined in the watchlist.
    """
    if len(recent_prices) >= 10:
        prices = sorted(recent_prices)
        n = len(prices)
        
        # Calculate trim index (15%)
        trim_idx = int(n * 0.15)
        
        # Guard to keep at least some elements
        if n - 2 * trim_idx >= 5:
            trimmed = prices[trim_idx : n - trim_idx]
        else:
            trimmed = prices
            
        m_min = min(trimmed)
        m_max = max(trimmed)
        
        # Median calculation
        mid = len(trimmed) // 2
        if len(trimmed) % 2 == 0:
            m_median = (trimmed[mid - 1] + trimmed[mid]) / 2.0
        else:
            m_median = float(trimmed[mid])
            
        # Confidence increases with volume
        confidence = min(0.95, 0.70 + (len(prices) - 10) * 0.01)
    else:
        # Fallback to watchlist config
        normal_range = watch_item.get("normal_price_range", [0, 0])
        m_min = normal_range[0]
        m_max = normal_range[1]
        m_median = sum(normal_range) / 2.0
        confidence = 0.50
        
    return {
        "market_min": int(m_min),
        "market_median": int(m_median),
        "market_max": int(m_max),
        "confidence": round(confidence, 2)
    }
