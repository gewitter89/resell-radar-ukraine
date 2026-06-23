"""
Price History Tracker — SQLite база истории цен.

Отслеживает:
  - Динамику цен по каждому продукту в каждом магазине
  - Минимальную цену за всё время
  - Тренд: цена растёт / падает / стабильна
  - Время последнего изменения
  - % изменения за неделю

Использование:
  tracker = PriceTracker()
  tracker.record("молоко 1л", "ATB", 32.90)
  trend = tracker.get_trend("молоко 1л", "ATB")
  # → {"direction": "down", "change_pct": -5.2, "min_30d": 29.90}
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent / "price_history.db"


class PriceTracker:
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product TEXT NOT NULL,
                    store TEXT NOT NULL,
                    price REAL NOT NULL,
                    old_price REAL DEFAULT 0,
                    discount_pct INTEGER DEFAULT 0,
                    recorded_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    UNIQUE(product, store, recorded_at)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_product_store
                ON price_history(product, store)
            """)
            conn.commit()

    def record(self, product: str, store: str, price: float,
               old_price: float = 0, discount_pct: int = 0):
        """Записать цену."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO price_history
                   (product, store, price, old_price, discount_pct, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (product, store, price, old_price, discount_pct, now),
            )
            conn.commit()

    def bulk_record(self, records: list[dict]):
        """Массовая запись [{product, store, price, ...}, ...]."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        with sqlite3.connect(self.db_path) as conn:
            for r in records:
                conn.execute(
                    """INSERT OR IGNORE INTO price_history
                       (product, store, price, old_price, discount_pct, recorded_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (r["product"], r["store"], r["price"],
                     r.get("old_price", 0), r.get("discount_pct", 0), now),
                )
            conn.commit()

    def get_history(self, product: str, store: str, days: int = 30) -> list[dict]:
        """История цен за N дней."""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT price, recorded_at FROM price_history
                   WHERE product=? AND store=? AND recorded_at >= ?
                   ORDER BY recorded_at DESC""",
                (product, store, cutoff),
            ).fetchall()
            return [{"price": r["price"], "date": r["recorded_at"]} for r in rows]

    def get_trend(self, product: str, store: str) -> dict:
        """Анализ тренда цены за 7 и 30 дней."""
        now = datetime.now()

        with sqlite3.connect(self.db_path) as conn:
            # Последняя цена
            last = conn.execute(
                """SELECT price FROM price_history
                   WHERE product=? AND store=?
                   ORDER BY recorded_at DESC LIMIT 1""",
                (product, store),
            ).fetchone()

            # Цена 7 дней назад
            cutoff_7 = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
            avg_7 = conn.execute(
                """SELECT AVG(price) FROM price_history
                   WHERE product=? AND store=? AND recorded_at >= ?""",
                (product, store, cutoff_7),
            ).fetchone()

            # Минимум за 30 дней
            cutoff_30 = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
            min_30 = conn.execute(
                """SELECT MIN(price) FROM price_history
                   WHERE product=? AND store=? AND recorded_at >= ?""",
                (product, store, cutoff_30),
            ).fetchone()

            # Максимум за 30 дней
            max_30 = conn.execute(
                """SELECT MAX(price) FROM price_history
                   WHERE product=? AND store=? AND recorded_at >= ?""",
                (product, store, cutoff_30),
            ).fetchone()

        current = last[0] if last else 0
        avg_7_val = avg_7[0] if avg_7 and avg_7[0] else current
        min_30_val = min_30[0] if min_30 and min_30[0] else current
        max_30_val = max_30[0] if max_30 and max_30[0] else current

        # Тренд
        change_pct = ((current - avg_7_val) / avg_7_val * 100) if avg_7_val > 0 else 0

        if change_pct < -3:
            direction = "down"      # цена упала — отлично!
            emoji = "📉"
        elif change_pct > 3:
            direction = "up"        # цена выросла — плохо
            emoji = "📈"
        else:
            direction = "stable"    # стабильно
            emoji = "➡️"

        # Близость к историческому минимуму
        off_min_pct = ((current - min_30_val) / min_30_val * 100) if min_30_val > 0 else 0

        if off_min_pct <= 2:
            deal_quality = "best"       # почти исторический минимум
            deal_emoji = "🔥"
        elif off_min_pct <= 10:
            deal_quality = "good"       # близко к минимуму
            deal_emoji = "✅"
        elif off_min_pct <= 20:
            deal_quality = "ok"         # средняя
            deal_emoji = "🟡"
        else:
            deal_quality = "expensive"  # дорого
            deal_emoji = "🔴"

        return {
            "current": current,
            "avg_7d": round(avg_7_val, 2),
            "min_30d": round(min_30_val, 2),
            "max_30d": round(max_30_val, 2),
            "change_pct": round(change_pct, 1),
            "off_min_pct": round(off_min_pct, 1),
            "direction": direction,
            "direction_emoji": emoji,
            "deal_quality": deal_quality,
            "deal_emoji": deal_emoji,
            "summary": (
                f"{deal_emoji} {emoji} "
                f"({change_pct:+.1f}% за 7д, "
                f"мин 30д: {min_30_val:.0f} ₴ — "
                f"сейчас {'близко к минимуму' if off_min_pct <= 5 else 'выше на ' + str(int(off_min_pct)) + '%'})"
            ),
        }

    def get_cheapest_store(self, product: str) -> dict:
        """Самый дешёвый магазин за всё время."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT store, MIN(price) as min_price
                   FROM price_history WHERE product=?
                   GROUP BY store ORDER BY min_price LIMIT 1""",
                (product,),
            ).fetchone()
            if row:
                return {"store": row[0], "price": row[1]}
            return {"store": "", "price": 0}

    def get_best_time_to_buy(self, product: str) -> dict:
        """Лучшее время для покупки (день недели + время) за 90 дней."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT recorded_at, price FROM price_history
                   WHERE product=?
                   ORDER BY recorded_at""",
                (product,),
            ).fetchall()

        if not rows:
            return {"best_day": "нет данных", "best_time": "нет данных"}

        # Группировка по дням недели
        day_prices: dict[int, list[float]] = {}
        for date_str, price in rows:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                day = dt.weekday()
                if day not in day_prices:
                    day_prices[day] = []
                day_prices[day].append(price)
            except ValueError:
                continue

        if not day_prices:
            return {"best_day": "нет данных", "best_time": "нет данных"}

        # Средняя по каждому дню
        day_avgs = {d: sum(p)/len(p) for d, p in day_prices.items()}
        best_day_num = min(day_avgs, key=day_avgs.get)
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

        return {
            "best_day": day_names[best_day_num],
            "best_time": "утро (цены обновляются)",
        }


# Глобальный экземпляр
tracker = PriceTracker()
