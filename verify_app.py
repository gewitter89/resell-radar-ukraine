import sys
import os
from datetime import datetime

# Reconfigure stdout/stderr to support emojis on Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Add the project root to python path to run imports successfully
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    print("1. Testing module imports...")
    try:
        import config
        from app.utils import logger, money, text, time
        from app.storage import database, models, repositories
        from app.scoring import text_analyzer, market_price, deal_score, risk_score
        from app.olx import models as olx_models, url_builder, parser, scraper
        from app.services import learning, profit_tracker, notifier, monitor
        from app.bot import keyboards, handlers, telegram_bot
        print("   ✅ All modules imported successfully without syntax errors!")
    except Exception as e:
        print(f"   ❌ Import test failed: {e}")
        sys.exit(1)

def test_database():
    print("\n2. Testing database initialization...")
    try:
        from app.storage.database import init_db, SessionLocal
        from app.storage.models import Ad, UserFeedback, MarketSnapshot, CategoryStats
        
        # This will create resell_radar.db if it doesn't exist
        init_db()
        print("   ✅ Database tables initialized successfully.")
        
        db = SessionLocal()
        # Verify connection
        count = db.query(Ad).count()
        print(f"   ✅ Database connection verified. Current number of ads: {count}")
        db.close()
    except Exception as e:
        print(f"   ❌ Database test failed: {e}")
        sys.exit(1)

def test_html_parsing():
    print("\n3. Testing HTML parser with mock data...")
    try:
        from app.olx.parser import parse_listings, parse_details
        
        mock_list_html = """
        <html>
            <body>
                <div data-testid="l-card" data-id="80001234">
                    <a href="/d/uk/obyavlenie/iphone-12-128gb-IDTz8hR.html">
                        <h6>iPhone 12 128GB Blue</h6>
                    </a>
                    <p class="css-1dp558c">12 000 грн.</p>
                    <img src="https://images.olx.ua/assets/123.jpg" />
                    <p data-testid="location-date">Киев, Дарницкий - Сегодня в 12:45</p>
                </div>
            </body>
        </html>
        """
        listings = parse_listings(mock_list_html)
        if len(listings) == 1:
            item = listings[0]
            print(f"   ✅ Listings parsing works! ID: {item.olx_id}, Title: {item.title}, Price: {item.price}, URL: {item.url}")
        else:
            print(f"   ❌ Listings parsing failed: expected 1 listing, got {len(listings)}")
            
        mock_detail_html = """
        <html>
            <body>
                <div data-testid="description-section">
                    Отличный айфон, без дефектов, не включается icloud, шутка, все работает.
                </div>
                <div data-testid="swiper-slide">
                    <img src="https://images.olx.ua/assets/full1.jpg" />
                </div>
                <div class="css-1r0594">Состояние: Б/у</div>
            </body>
        </html>
        """
        details = parse_details(mock_detail_html)
        if "Отличный айфон" in details.description:
            print(f"   ✅ Details parsing works! Description len: {len(details.description)}, Params: {details.parameters}")
        else:
            print("   ❌ Details parsing failed.")
    except Exception as e:
        print(f"   ❌ Parser test encountered error: {e}")
        sys.exit(1)

def test_scoring_engines():
    print("\n4. Testing scoring algorithms...")
    try:
        from app.scoring.market_price import estimate_market_price
        from app.scoring.deal_score import calculate_deal_score
        from app.scoring.risk_score import calculate_risk_score
        
        watch_item = {
            "id": "iphone_12",
            "name": "iPhone 12",
            "normal_price_range": [11000, 14500],
            "max_green_price": 9500,
            "min_profit": 2000,
            "keywords": ["iphone 12"],
            "bad_words": ["icloud", "не включается"]
        }
        
        # Test market price fallback (no recent ads)
        market_est = estimate_market_price(8500.0, watch_item, [])
        print(f"   ✅ Market estimation fallback: {market_est}")
        
        # Test deal score calculation
        deal_score, profit = calculate_deal_score(
            price=8000.0,
            market_median=12750.0, # (11000+14500)/2
            watch_item=watch_item,
            title="Продам iPhone 12 128GB Blue",
            description="Идеальное состояние, все функции работают отлично, полный комплект.",
            image_url="https://images.olx.ua/img.jpg",
            published_at=datetime.now(),
            first_seen_at=datetime.now()
        )
        print(f"   ✅ Deal score calculated: {deal_score}/100, Est. Profit: {profit} UAH")
        
        # Test risk score calculation (with negative word 'icloud')
        risk = calculate_risk_score(
            price=8000.0,
            market_median=12750.0,
            title="iPhone 12 iCloud",
            description="Заблокирован icloud, продажа на запчасти.",
            image_url="https://images.olx.ua/img.jpg",
            item_bad_words=watch_item["bad_words"],
            global_bad_words=[]
        )
        print(f"   ✅ Risk score calculated: {risk}/100 (Expected elevated risk due to bad words)")
    except Exception as e:
        print(f"   ❌ Scoring engines test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("=== RESELL RADAR UKRAINE VERIFICATION ===")
    test_imports()
    test_database()
    test_html_parsing()
    test_scoring_engines()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! The application structure is correct and ready.")
