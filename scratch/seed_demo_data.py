import sys
import os
from datetime import datetime, timedelta
import random

# Reconfigure stdout/stderr to support emojis on Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Add project root to system path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.storage.database import init_db, db_session
from app.storage.models import Ad, UserFeedback, CategoryStats, MarketSnapshot
from app.storage.repositories import CategoryStatsRepository, FeedbackRepository

def seed_database():
    print("=== SEEDING DEMO DATA FOR RESELL RADAR UKRAINE ===")
    init_db()
    
    with db_session() as session:
        # Clear existing data to avoid conflicts
        print("Clearing old records...")
        session.query(UserFeedback).delete()
        session.query(Ad).delete()
        session.query(CategoryStats).delete()
        session.query(MarketSnapshot).delete()
        
        print("Seeding mock ads and feedbacks...")
        
        # Define some mock items across categories
        mock_data = [
            # Phones
            {
                "olx_id": "812345678",
                "title": "iPhone 11 128GB Black Neverlock идеальное состояние",
                "price": 6000,
                "url": "https://www.olx.ua/d/uk/obyavlenie/iphone-11-128gb-black-neverlock-IDTz8hA.html",
                "location": "Киев, Шевченковский",
                "description": "Продам свой телефон в отличном состоянии. Не бит, не крашен, батарея 85%. Все функции работают, Face ID, True Tone.",
                "image_url": "https://images.olx.ua/assets/iphone11.jpg",
                "category": "phones",
                "watch_item_id": "iphone_11",
                "deal_score": 88,
                "risk_score": 15,
                "estimated_market_price": 9500,
                "estimated_profit": 3500,
                "status": "sold",
                "buy_price": 6000,
                "sell_price": 9000,
            },
            {
                "olx_id": "812345679",
                "title": "Шуруповерт Makita DDF453 + АКБ и Зарядка",
                "price": 2200,
                "url": "https://www.olx.ua/d/uk/obyavlenie/makita-ddf453-IDTz8hB.html",
                "location": "Харьков, Киевский",
                "description": "Продам оригинальный шуруповерт Макита. Полностью исправный. В комплекте кейс, зарядное и один аккумулятор 3Ач.",
                "image_url": "https://images.olx.ua/assets/makita.jpg",
                "category": "tools",
                "watch_item_id": "makita_tools",
                "deal_score": 92,
                "risk_score": 10,
                "estimated_market_price": 4200,
                "estimated_profit": 2000,
                "status": "sold",
                "buy_price": 2200,
                "sell_price": 3800,
            },
            {
                "olx_id": "812345680",
                "title": "PlayStation 5 (PS5) Blu-Ray 825GB лимитированная",
                "price": 12500,
                "url": "https://www.olx.ua/d/uk/obyavlenie/playstation-5-ps5-blu-ray-825gb-IDTz8hC.html",
                "location": "Одесса, Приморский",
                "description": "Игровая приставка Сони Плейстейшн 5 с дисководом. Не шумит, не греется, не забанена в PSN. Полный комплект с коробкой и чеком.",
                "image_url": "https://images.olx.ua/assets/ps5.jpg",
                "category": "gaming",
                "watch_item_id": "ps5",
                "deal_score": 86,
                "risk_score": 20,
                "estimated_market_price": 18500,
                "estimated_profit": 6000,
                "status": "sold",
                "buy_price": 12500,
                "sell_price": 17200,
            },
            {
                "olx_id": "812345681",
                "title": "MacBook Air M1 2020 8/256 Space Gray идеальный",
                "price": 14000,
                "url": "https://www.olx.ua/d/uk/obyavlenie/macbook-air-m1-2020-8-256-IDTz8hD.html",
                "location": "Львов, Галицкий",
                "description": "Макбук в прекрасном состоянии, углы целые, экран без царапин. Износ батареи 91%, держит очень долго. Без MDM и iCloud блокировок.",
                "image_url": "https://images.olx.ua/assets/macbook.jpg",
                "category": "laptops",
                "watch_item_id": "macbook_air",
                "deal_score": 90,
                "risk_score": 15,
                "estimated_market_price": 22000,
                "estimated_profit": 8000,
                "status": "bought",
                "buy_price": 14000,
            },
            {
                "olx_id": "812345682",
                "title": "Коляска Cybex Priam 2в1 Soho Grey премиум",
                "price": 7500,
                "url": "https://www.olx.ua/d/uk/obyavlenie/cybex-priam-2v1-soho-grey-IDTz8hE.html",
                "location": "Днепр, Соборный",
                "description": "Коляска после одного ребенка, рама Chrome, текстиль в идеале. Все механизмы работают отлично, маневренная и удобная.",
                "image_url": "https://images.olx.ua/assets/cybex.jpg",
                "category": "kids",
                "watch_item_id": "cybex_stroller",
                "deal_score": 82,
                "risk_score": 25,
                "estimated_market_price": 13500,
                "estimated_profit": 6000,
                "status": "bought",
                "buy_price": 7500,
            },
            {
                "olx_id": "812345683",
                "title": "Электросамокат Xiaomi Mi Scooter 1S оригинальный",
                "price": 5500,
                "url": "https://www.olx.ua/d/uk/obyavlenie/xiaomi-mi-scooter-1s-IDTz8hF.html",
                "location": "Киев, Оболонь",
                "description": "Оригинальный самокат Сяоми. Пробег небольшой. Батарея держит отлично, запас хода до 30 км. В комплекте зарядка.",
                "image_url": "https://images.olx.ua/assets/scooter.jpg",
                "category": "transport",
                "watch_item_id": "xiaomi_scooter",
                "deal_score": 85,
                "risk_score": 15,
                "estimated_market_price": 9500,
                "estimated_profit": 4000,
                "status": "interesting",
            },
            {
                "olx_id": "812345684",
                "title": "Велосипед Giant Escape 2 Disc M-размер",
                "price": 6000,
                "url": "https://www.olx.ua/d/uk/obyavlenie/giant-escape-2-disc-IDTz8hG.html",
                "location": "Запорожье, Вознесеновский",
                "description": "Городской гибрид Giant. Дисковые тормоза Tektro, трансмиссия Shimano Altus. Отличное состояние, сел и поехал.",
                "image_url": "https://images.olx.ua/assets/giant.jpg",
                "category": "bikes",
                "watch_item_id": "giant_bike",
                "deal_score": 79,
                "risk_score": 20,
                "estimated_market_price": 11000,
                "estimated_profit": 5000,
                "status": "new",
            },
            {
                "olx_id": "812345685",
                "title": "Кроссовки Nike Air Max 90 42 размер новые",
                "price": 1200,
                "url": "https://www.olx.ua/d/uk/obyavlenie/nike-air-max-90-IDTz8hH.html",
                "location": "Винница, Ленинский",
                "description": "Новые оригинальные кроссовки Найк. Привезли из Германии, не подошел размер. Коробка без крышки.",
                "image_url": "https://images.olx.ua/assets/nike.jpg",
                "category": "clothes",
                "watch_item_id": "nike_shoes",
                "deal_score": 87,
                "risk_score": 15,
                "estimated_market_price": 3800,
                "estimated_profit": 2600,
                "status": "new",
            },
            {
                "olx_id": "812345686",
                "title": "iPhone 12 128GB R-SIM Не работает Face ID",
                "price": 5000,
                "url": "https://www.olx.ua/d/uk/obyavlenie/iphone-12-rsim-no-face-IDTz8hI.html",
                "location": "Полтава, Октябрьский",
                "description": "Продам айфон 12 на 128гб. Работает через чип R-sim. Face ID сломан после падения, экран менялся на копию. Батарея 72%.",
                "image_url": "https://images.olx.ua/assets/iphone12_bad.jpg",
                "category": "phones",
                "watch_item_id": "iphone_12",
                "deal_score": 45,
                "risk_score": 65,
                "estimated_market_price": 12500,
                "estimated_profit": 7500,
                "status": "trash",
            },
            {
                "olx_id": "812345687",
                "title": "Конструктор LEGO Creator Эксперт 10265 Ford Mustang",
                "price": 1300,
                "url": "https://www.olx.ua/d/uk/obyavlenie/lego-creator-ford-mustang-10265-IDTz8hJ.html",
                "location": "Чернигов, Деснянский",
                "description": "Лего Форд Мустанг оригинальный конструктор в собранном виде. Комплект полный, есть коробка и инструкция. Пылился на полке.",
                "image_url": "https://images.olx.ua/assets/lego.jpg",
                "category": "toys",
                "watch_item_id": "lego",
                "deal_score": 90,
                "risk_score": 10,
                "estimated_market_price": 3800,
                "estimated_profit": 2500,
                "status": "sold",
                "buy_price": 1300,
                "sell_price": 3200,
            }
        ]
        
        for item in mock_data:
            ad = Ad(
                olx_id=item["olx_id"],
                title=item["title"],
                price=item["price"],
                url=item["url"],
                location=item["location"],
                description=item["description"],
                image_url=item["image_url"],
                category=item["category"],
                watch_item_id=item["watch_item_id"],
                deal_score=item["deal_score"],
                risk_score=item["risk_score"],
                estimated_market_price=item["estimated_market_price"],
                estimated_profit=item["estimated_profit"],
                status=item["status"],
                sent_to_telegram=True,
                published_at=datetime.utcnow() - timedelta(hours=random.randint(1, 48)),
                first_seen_at=datetime.utcnow() - timedelta(hours=random.randint(1, 48)),
                created_at=datetime.utcnow() - timedelta(hours=random.randint(1, 48)),
            )
            session.add(ad)
            session.flush() # Populate ad.id
            
            # Seed Feedback & Category Stats
            category = item["category"]
            status = item["status"]
            
            if status == "interesting":
                feedback = UserFeedback(ad_id=ad.id, action="interesting")
                session.add(feedback)
            elif status == "trash":
                feedback = UserFeedback(ad_id=ad.id, action="trash")
                session.add(feedback)
                CategoryStatsRepository.increment_stats(session, category, trash=1)
            elif status == "bought":
                feedback = UserFeedback(ad_id=ad.id, action="bought")
                session.add(feedback)
                CategoryStatsRepository.increment_stats(session, category, bought=1)
            elif status == "sold":
                buy_price = item["buy_price"]
                sell_price = item["sell_price"]
                profit = sell_price - buy_price
                roi = (profit / buy_price) * 100.0 if buy_price > 0 else 0.0
                
                feedback = UserFeedback(
                    ad_id=ad.id,
                    action="sold",
                    buy_price=buy_price,
                    sell_price=sell_price,
                    profit=profit,
                    roi=roi
                )
                session.add(feedback)
                # First increment as bought (since we must have bought it before selling)
                CategoryStatsRepository.increment_stats(session, category, bought=1)
                # Then increment as sold with profit
                CategoryStatsRepository.increment_stats(session, category, sold=1, profit=profit)
                
            # Increment sent stats
            CategoryStatsRepository.increment_stats(session, category, sent=1)
            
            # Create some dummy market snapshots for history
            for price_offset in [-1000, -500, 0, 500, 1000, 1500]:
                snap = MarketSnapshot(
                    watch_item_id=item["watch_item_id"],
                    title=item["title"],
                    price=item["estimated_market_price"] + price_offset,
                    url=item["url"]
                )
                session.add(snap)
                
        session.commit()
        print("✅ Seeding completed successfully!")
        
if __name__ == "__main__":
    seed_database()
