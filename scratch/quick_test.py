"""Quick smoke test for core modules."""
import sys
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from app.olx.parser import parse_listings
from app.scoring.deal_score import calculate_deal_score
from app.scoring.risk_score import calculate_risk_score
from datetime import datetime

# Test 1: HTML parsing
mock_html = """<html><body>
<div data-testid="l-card">
<a href="/d/uk/obyavlenie/test-ID123.html"><h6>iPhone 12 128GB</h6></a>
<p class="css-1dp558c">12 000 грн.</p>
<img src="https://img.olx.ua/1.jpg"/>
</div></body></html>"""

ads = parse_listings(mock_html)
assert len(ads) == 1, f"Expected 1 ad, got {len(ads)}"
assert ads[0].title == "iPhone 12 128GB"
print(f"[PASS] Parse: {ads[0].title} @ {ads[0].price} UAH")

# Test 2: Deal score
wi = {"normal_price_range": [11000, 14500], "max_green_price": 9500, "keywords": ["iphone 12"]}
ds, profit = calculate_deal_score(
    8000, 12750, wi,
    title="iPhone 12 128GB Blue",
    description="Ideal state, full set, all functions work.",
    image_url="http://img.jpg",
    published_at=datetime.now(),
)
assert ds > 50, f"Deal score too low: {ds}"
print(f"[PASS] Deal score: {ds}/100, profit: {profit} UAH")

# Test 3: Risk score
rs = calculate_risk_score(
    8000, 12750,
    title="iPhone 12 iCloud",
    description="Blocked icloud, sell for parts.",
    image_url="http://img.jpg",
    item_bad_words=["icloud", "не включается"],
    global_bad_words=[],
)
assert rs > 30, f"Risk score too low: {rs}"
print(f"[PASS] Risk score: {rs}/100")

# Test 4: Market price (no recent data = use fallback)
from app.scoring.market_price import estimate_market_price
mp = estimate_market_price(8000, wi, [])
assert mp["market_median"] > 0
print(f"[PASS] Market price: median={mp['market_median']}, confidence={mp['confidence']}")

print("\n=== ALL CORE TESTS PASSED ===")
