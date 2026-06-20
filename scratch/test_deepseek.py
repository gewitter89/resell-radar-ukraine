"""
Live DeepSeek AI Analyzer Test
Tests with realistic OLX listings including the tricky cases the user mentioned:
- "стекло на iPhone 11" (not a phone, but glass protector)
- iPhone with wrong model labeling
- Real price accuracy check
"""

import asyncio
import sys

# Reconfigure stdout/stderr to support emojis on Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, 'c:/Users/HOMEH/Desktop/БОТЫ/ОЛХ/resell_radar')

from app.scoring.ai_analyzer import analyze_listing_with_ai
from config import settings

async def run_tests():
    print(f"DeepSeek key set: {bool(settings.deepseek_api_key)}")
    print(f"Key preview: {settings.deepseek_api_key[:8]}...{settings.deepseek_api_key[-4:]}")
    print()

    test_cases = [
        {
            "name": "🧪 TEST 1: Стекло (не телефон!) продается под видом аксессуара",
            "title": "стекло на iPhone 11",
            "description": "Продаю защитное стекло на Айфон 11. Подходит для моделей iPhone 11, XR. Упаковано, не использовалось.",
            "expect_low_score": True,
            "expect_correction": True,
        },
        {
            "name": "🧪 TEST 2: iPhone 7 лейблован как iPhone 11 (ошибка продавца)",
            "title": "iPhone 11 продаю срочно",
            "description": "Продаю айфон, экран 4.7 дюйма, 2 камеры нет, одна камера сзади. Диагональ маленькая. Айфон 7 или около того, точно не помню модель.",
            "expect_correction": True,
        },
        {
            "name": "🧪 TEST 3: Хороший iPhone 13 без дефектов",
            "title": "iPhone 13 128GB состояние отличное",
            "description": "Продаю iPhone 13, 128GB, цвет синий. Куплен в официальном магазине Украина. Аккумулятор 91%. Face ID работает. Комплект полный: коробка, кабель. Без царапин, стекло целое. Причина продажи - купил 14 Pro.",
            "expect_high_score": True,
        },
        {
            "name": "🧪 TEST 4: iPhone с iCloud блокировкой (риск!)",
            "title": "iPhone 12 дешево срочно",
            "description": "Айфон 12, не включается, iCloud, куплен как есть, на запчасти или восстановление. После воды. Разбит экран.",
        },
        {
            "name": "🧪 TEST 5: MacBook Air (реальное объявление)",
            "title": "MacBook Air M1 2020 256GB",
            "description": "MacBook Air M1, 2020 год, 8GB RAM, 256GB SSD. Состояние хорошее, небольшие царапины на корпусе. Аккумулятор держит 7-8 часов. macOS Sonoma. Продаю в связи с переходом на Mac Pro.",
            "expect_high_score": True,
        },
        {
            "name": "🧪 TEST 6: Телефон с R-SIM (блокировка оператора)",
            "title": "iPhone 12 USA 64GB",
            "description": "Айфон 12 из США, работает с R-SIM переходником. Залочен на оператора AT&T. Внешне в хорошем состоянии. Всё работает через R-sim.",
        },
    ]

    for tc in test_cases:
        print("=" * 60)
        print(tc["name"])
        print(f"  Название: {tc['title']}")
        print(f"  Описание: {tc['description'][:100]}...")
        print()

        result = await analyze_listing_with_ai(tc["title"], tc["description"])

        print(f"  ✅ Condition Score:  {result['condition_score']}/100")
        print(f"  ✅ Corrected Name:   {result['product_name_corrected']}")
        print(f"  ✅ Дефекты:          {result['defects'] or 'Не найдены'}")
        print(f"  ✅ Вердикт:          {result['verdict']}")
        print()

        # Validate expectations
        if tc.get("expect_low_score") and result["condition_score"] >= 80:
            print(f"  ⚠️  WARN: Expected low score, got {result['condition_score']}")

        if tc.get("expect_high_score") and result["condition_score"] < 70:
            print(f"  ⚠️  WARN: Expected high score, got {result['condition_score']}")

        if tc.get("expect_correction") and result["product_name_corrected"].lower() == tc["title"].lower():
            print(f"  ⚠️  WARN: Expected corrected title, but got same: '{result['product_name_corrected']}'")
        elif tc.get("expect_correction"):
            print(f"  ✅ Name was corrected: '{tc['title']}' → '{result['product_name_corrected']}'")

    print()
    print("=" * 60)
    print("ALL AI TESTS COMPLETE!")
    print("=" * 60)

asyncio.run(run_tests())
