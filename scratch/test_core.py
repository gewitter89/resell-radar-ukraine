import sys
# Reconfigure stdout/stderr to support emojis on Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, 'c:/Users/HOMEH/Desktop/БОТЫ/ОЛХ/resell_radar')

print('=== TEST 1: Deal Score Calculation ===')
from app.scoring.deal_score import calculate_deal_score
from datetime import datetime, timedelta

watch_item = {
    'keywords': ['iphone 11', 'айфон 11'],
    'max_green_price': 7000,
    'normal_price_range': [8500, 11500],
    'bad_words': ['icloud', 'копия']
}

score, profit = calculate_deal_score(
    price=6500,
    market_median=10000,
    watch_item=watch_item,
    title='iPhone 11 64GB в хорошем состоянии',
    description='Продаю iPhone 11, 64GB, состояние 9/10, аккумулятор 87%. Полный комплект, чехол в подарок. Работает отлично.',
    image_url='http://example.com/img.jpg',
    published_at=datetime.utcnow() - timedelta(minutes=5),
    ai_condition_score=88
)
print(f'  Price 6500 vs market 10000: Score={score}/100, Profit={profit:.0f} UAH')
assert score >= 75, f'Expected score >= 75, got {score}'
print('  PASS')

print()
print('=== TEST 2: Risk Score Calculation ===')
from app.scoring.risk_score import calculate_risk_score

risk = calculate_risk_score(
    price=6500,
    market_median=10000,
    title='iPhone 11 64GB',
    description='Продаю iPhone 11, 64GB. Аккумулятор 87%. Все работает.',
    image_url='http://example.com/img.jpg',
    watch_item=watch_item,
    ai_defects=[]
)
print(f'  Clean listing risk: {risk}/100')
assert risk < 30, f'Expected risk < 30, got {risk}'
print('  PASS')

risk_bad = calculate_risk_score(
    price=6500,
    market_median=10000,
    title='iPhone 11 iCloud lock после воды',
    description='icloud, не включается',
    image_url=None,
    watch_item=watch_item,
    ai_defects=['iCloud lock', 'water damage']
)
print(f'  Bad listing risk: {risk_bad}/100')
assert risk_bad > 50, f'Expected risk > 50, got {risk_bad}'
print('  PASS')

print()
print('=== TEST 3: Market Price Estimation ===')
from app.scoring.market_price import estimate_market_price

result = estimate_market_price(6500, watch_item, [])
median = result["market_median"]
confidence = result["confidence"]
print(f'  Fallback (no data): median={median}, confidence={confidence}')
assert median == 10000, f'Expected 10000, got {median}'

prices = [7000, 8000, 8500, 9000, 9500, 10000, 10500, 11000, 11500, 12000, 13000, 13500]
result2 = estimate_market_price(6500, watch_item, prices)
med2 = result2["market_median"]
conf2 = result2["confidence"]
print(f'  With 12 data points: median={med2}, confidence={conf2}')
assert conf2 >= 0.72, f'Expected confidence >= 0.72, got {conf2}'
print('  PASS')

print()
print('=== TEST 4: Text Similarity ===')
from app.utils.text import get_similarity_ratio
ratio = get_similarity_ratio('iPhone 11 продается', 'iPhone 11 продаётся')
print(f'  Similar texts ratio: {ratio:.2f}')
assert ratio >= 0.85
ratio2 = get_similarity_ratio('Мяч футбольный Adidas', 'iPhone 11 Apple телефон')
print(f'  Different texts ratio: {ratio2:.2f}')
assert ratio2 < 0.5
print('  PASS')

print()
print('=== TEST 5: Watchlist Loading ===')
from app.services.monitor import load_watchlist
wl = load_watchlist()
print(f'  Loaded {len(wl)} watchlist items')
assert len(wl) > 0
for item in wl:
    assert 'id' in item and 'search_url' in item and 'keywords' in item, f'Missing keys in {item}'
print('  PASS')

print()
print('=== TEST 6: DB Repository ===')
from app.storage.database import db_session
from app.storage.models import Ad
from app.storage.repositories import AdRepository, FeedbackRepository
with db_session() as session:
    total = session.query(Ad).count()
    sent = session.query(Ad).filter(Ad.sent_to_telegram == True).count()
    fin = FeedbackRepository.get_financial_summary(session)
    print(f'  Ads in DB: {total}, Sent: {sent}')
    print(f'  Financial: profit={fin["total_profit"]}, roi={fin["avg_roi"]:.1f}%')
    print('  PASS')

print()
print('=== TEST 7: Money Utils ===')
from app.utils.money import clean_price, format_price
assert clean_price('7 500 грн') == 7500
assert clean_price('12,000 UAH') == 12000
assert clean_price('0') == 0
assert format_price(7500) == '7 500 грн'
print('  clean_price & format_price: PASS')

print()
print('=== TEST 8: OLX URL Builder ===')
from app.olx.url_builder import clean_and_build_url
url = clean_and_build_url('https://www.olx.ua/uk/list/q-iphone-11/?search%5Border%5D=created_at:desc')
assert 'olx.ua' in url
print(f'  URL: {url}')
print('  PASS')

print()
print('=== TEST 9: OLX ID Extraction ===')
from app.olx.parser import extract_olx_id
olx_id = extract_olx_id('https://www.olx.ua/d/uk/obyavlenie/iphone-11-IDj3MNx.html')
print(f'  Extracted OLX ID: {olx_id}')
assert olx_id == 'j3MNx', f'Expected j3MNx, got {olx_id}'
print('  PASS')

print()
print('=== TEST 10: Keyboard Generation ===')
from app.bot.keyboards import get_deal_keyboard
kb = get_deal_keyboard(42)
assert kb is not None
buttons = [btn.text for row in kb.inline_keyboard for btn in row]
print(f'  Keyboard buttons: {buttons}')
assert any('Купил' in b for b in buttons)
assert any('Мусор' in b for b in buttons)
assert any('Продал' in b for b in buttons)
assert any('OLX' in b for b in buttons)
print('  PASS')

print()
print('=================================================================')
print('ALL 10 TESTS PASSED - Core logic is functioning correctly!')
print('=================================================================')
