"""
AI-powered listing analyzer for Resell Radar Ukraine.

Priority order:
1. DeepSeek Chat API (deepseek-chat model) — smart, understands Ukrainian/Russian product context
2. Google Gemini 1.5 Flash — fallback if DeepSeek key not set
3. Rule-based fallback — if neither key is configured

The AI evaluates:
  - condition_score: 0–100 product condition estimate
  - defects: list of detected flaws / flags (iCloud lock, repair, water damage, etc.)
  - verdict: short Russian/Ukrainian expert opinion on whether it's worth buying to resell
  - product_name_corrected: corrects a mis-stated model in the title (e.g. "iPhone 7" labeled as "11")
"""

import json
import httpx
from config import settings
from app.utils.logger import logger

# ── Shared prompt builder ────────────────────────────────────────────────────

def _build_prompt(title: str, description: str, price: float = 0) -> str:
    return (
        "Ты — опытный украинский перекупщик техники и товаров. "
        "Проанализируй следующее объявление с OLX Украина.\n\n"
        f"Название объявления: {title}\n"
        f"Описание: {description}\n"
        f"Цена продавца: {int(price)} грн\n\n"
        "Выполни следующие задачи:\n"
        "1. Оцени состояние товара от 0 до 100 (100 = новое/идеальное, 0 = хлам/запчасти).\n"
        "2. Определи ТИП состояния: 'new' (новый, запечатан), 'used_like_new' (б/у как новый), "
        "'used_good' (б/у хорошее), 'used_defects' (б/у с дефектами), 'for_parts' (на запчасти).\n"
        "3. Выдели ВСЕ скрытые и явные дефекты, ремонты, следы воды, iCloud/MDM/R-SIM блокировки, неоригинальные детали.\n"
        "   Если в тексте объявления есть намёк на проблемы ('не проверял', 'как есть', 'без возврата') — добавь это в defects.\n"
        "4. Оцени РЕАЛЬНУЮ цену перепродажи в грн — за сколько реально продать этот товар "
        "на OLX Украине с учётом состояния, дефектов и текущего рынка. Укажи число в поле estimated_resell_price.\n"
        "5. Посчитай ожидаемую прибыль: estimated_resell_price минус цена продавца. "
        "Укажи в поле expected_profit.\n"
        "6. Оцени ликвидность: 'instant' (уйдёт за часы), 'fast' (1-3 дня), "
        "'normal' (до 2 недель), 'slow' (до месяца), 'hard' (месяц+).\n"
        "7. Посоветуй СТАРТОВУЮ ЦЕНУ ДЛЯ ТОРГА (bargain_price) — с какой суммы начать переговоры, "
        "чтобы продавец не послал, но вы остались в плюсе. Обычно 70-85% от цены продавца.\n"
        "8. Оцени СРОЧНОСТЬ (urgency): насколько высока вероятность что этот товар купят "
        "в ближайшие часы другим перекупом. 'high' (улетит), 'medium' (средняя), 'low' (никто не спешит).\n"
        "9. Посчитай ЧИСТУЮ ПРИБЫЛЬ (net_profit) после вычета комиссий: "
        "OLX сервис (~1.5% от цены продажи), платежная система (~1.5%), упаковка (~50 грн), транспорт (~50 грн). "
        "Формула: net_profit = estimated_resell_price - price - olx_fee - payment_fee - packaging - transport.\n"
        "10. Оцени НАСЫЩЕННОСТЬ РЫНКА (market_saturation): сколько сейчас таких же товаров "
        "на OLX. 'low' (<10), 'medium' (10-50), 'high' (>50), 'very_high' (>100).\n"
        "11. Проверь корректность названия: если продавец написал неправильную модель, "
        "исправь в product_name_corrected. Если название корректно — верни как есть.\n"
        "12. ПРОАНАЛИЗИРУЙ ПРОДАВЦА: если в тексте есть признаки проблемного продавца "
        "(нет фото, нет описания, просит предоплату, новый аккаунт, "
        "только 1 объявление, странные формулировки) — укажи это в поле seller_risk "
        "('low', 'medium', 'high'). Укажи причины в seller_risk_reason.\n"
        "13. Определи СЕЗОННОСТЬ: насколько этот товар актуален сейчас на украинском рынке. "
        "'peak' (пик сезона — отлично продаётся), 'normal' (нормально), "
        "'off_season' (не сезон — будет продаваться дольше). Укажи в поле seasonality.\n"
        "14. ОЦЕНИ УВЕРЕННОСТЬ (confidence): насколько ты уверен в своих оценках. "
        "'high' (есть много данных), 'medium' (средняя уверенность), "
        "'low' (мало данных, предположение).\n"
        "15. Напиши ВЕРДИКТ (1-2 предложения, на русском): итоговая рекомендация "
        "с указанием чистой прибыли, торга, риска и сезонности.\n\n"
        "ВАЖНО: Верни ответ СТРОГО в формате JSON (без ```json блоков):\n"
        "{\n"
        '  "condition_type": "used_good",\n'
        '  "condition_score": 75,\n'
        '  "defects": ["легкие потертости на корпусе"],\n'
        '  "estimated_resell_price": 12000,\n'
        '  "expected_profit": 2000,\n'
        '  "net_profit": 1700,\n'
        '  "bargain_price": 8500,\n'
        '  "liquidity": "fast",\n'
        '  "urgency": "medium",\n'
        '  "market_saturation": "medium",\n'
        '  "seller_risk": "low",\n'
        '  "seller_risk_reason": "",\n'
        '  "seasonality": "normal",\n'
        '  "confidence": "high",\n'
        '  "product_name_corrected": "iPhone 12 128GB",\n'
        '  "verdict": "Стоит брать. Торгуйтесь с 8500 грн. После комиссий ~1700 грн чистыми. Сезон нормальный, продавец надёжный. Продастся за 1-3 дня."\n'
        "}"
    )

def _parse_ai_response(raw_text: str, title: str) -> dict:
    """Parses and validates the AI JSON response."""
    try:
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        result = json.loads(text)

        # ── condition_score ──────────────────────────────────────────
        if not isinstance(result.get("condition_score"), (int, float)):
            result["condition_score"] = 90
        result["condition_score"] = max(0, min(100, int(result["condition_score"])))

        # ── condition_type ──────────────────────────────────────────
        valid_types = {"new", "used_like_new", "used_good", "used_defects", "for_parts"}
        ct = result.get("condition_type", "used_good")
        if ct not in valid_types:
            ct = "used_good"
        result["condition_type"] = ct

        # ── defects ────────────────────────────────────────────────
        if not isinstance(result.get("defects"), list):
            result["defects"] = []

        # ── estimated_resell_price ──────────────────────────────────
        erp = result.get("estimated_resell_price", 0)
        if not isinstance(erp, (int, float)) or erp <= 0:
            result["estimated_resell_price"] = 0

        # ── expected_profit ─────────────────────────────────────────
        ep = result.get("expected_profit", 0)
        if not isinstance(ep, (int, float)):
            result["expected_profit"] = 0

        # ── liquidity ──────────────────────────────────────────────
        valid_liq = {"instant", "fast", "normal", "slow", "hard"}
        liq = result.get("liquidity", "normal")
        if liq not in valid_liq:
            liq = "normal"
        result["liquidity"] = liq

        # ── bargain_price ──────────────────────────────────────────
        bp = result.get("bargain_price", 0)
        if not isinstance(bp, (int, float)) or bp <= 0:
            result["bargain_price"] = 0

        # ── net_profit ─────────────────────────────────────────────
        np_profit = result.get("net_profit", 0)
        if not isinstance(np_profit, (int, float)):
            result["net_profit"] = result.get("expected_profit", 0)

        # ── urgency ────────────────────────────────────────────────
        valid_urg = {"high", "medium", "low"}
        urg = result.get("urgency", "medium")
        if urg not in valid_urg:
            urg = "medium"
        result["urgency"] = urg

        # ── market_saturation ──────────────────────────────────────
        valid_sat = {"low", "medium", "high", "very_high"}
        sat = result.get("market_saturation", "medium")
        if sat not in valid_sat:
            sat = "medium"
        result["market_saturation"] = sat

        # ── seller_risk ────────────────────────────────────────────
        valid_sr = {"low", "medium", "high"}
        sr = result.get("seller_risk", "low")
        if sr not in valid_sr:
            sr = "low"
        result["seller_risk"] = sr
        if not result.get("seller_risk_reason"):
            result["seller_risk_reason"] = ""

        # ── seasonality ────────────────────────────────────────────
        valid_seas = {"peak", "normal", "off_season"}
        seas = result.get("seasonality", "normal")
        if seas not in valid_seas:
            seas = "normal"
        result["seasonality"] = seas

        # ── confidence ─────────────────────────────────────────────
        valid_conf = {"high", "medium", "low"}
        conf = result.get("confidence", "medium")
        if conf not in valid_conf:
            conf = "medium"
        result["confidence"] = conf

        if not result.get("verdict"):
            result["verdict"] = "Анализ ИИ выполнен."

        if not result.get("product_name_corrected"):
            result["product_name_corrected"] = title

        return result

    except json.JSONDecodeError as e:
        logger.warning("AI response JSON parse error: {} | Raw: {}", e, raw_text[:200])
        return None


# ── DeepSeek analyzer ─────────────────────────────────────────────────────────

async def _analyze_with_deepseek(title: str, description: str, price: float = 0) -> dict | None:
    api_key = settings.deepseek_api_key
    if not api_key:
        return None

    prompt = _build_prompt(title, description, price)
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты — профессиональный оценщик товаров для перепродажи на украинском рынке. "
                    "Отвечай только валидным JSON без пояснений и markdown блоков."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data["choices"][0]["message"]["content"]
                result = _parse_ai_response(raw_text, title)
                if result:
                    logger.info(
                        "DeepSeek AI analysis OK for '{}'. Score: {}, Defects: {}",
                        title, result["condition_score"], result["defects"]
                    )
                    return result
            else:
                logger.warning("DeepSeek API error {}: {}", resp.status_code, resp.text[:300])
    except Exception as e:
        logger.error("DeepSeek API request failed: {}", e)

    return None


# ── Gemini analyzer ───────────────────────────────────────────────────────────

async def _analyze_with_gemini(title: str, description: str, price: float = 0) -> dict | None:
    api_key = settings.gemini_api_key
    if not api_key:
        return None

    prompt = _build_prompt(title, description, price)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                result = _parse_ai_response(raw_text, title)
                if result:
                    logger.info(
                        "Gemini AI analysis OK for '{}'. Score: {}",
                        title, result["condition_score"]
                    )
                    return result
            else:
                logger.warning("Gemini API error {}: {}", resp.status_code, resp.text[:300])
    except Exception as e:
        logger.error("Gemini API request failed: {}", e)

    return None


# ── Main public function ──────────────────────────────────────────────────────

async def analyze_listing_with_ai(title: str, description: str, price: float = 0) -> dict:
    """
    Analyzes a listing using available AI providers (DeepSeek first, Gemini as fallback).

    Returns:
        dict with keys:
            - condition_type (str): new/used_like_new/used_good/used_defects/for_parts
            - condition_score (int 0-100)
            - defects (list[str])
            - estimated_resell_price (int)
            - expected_profit (int)
            - liquidity (str): instant/fast/normal/slow/hard
            - product_name_corrected (str)
            - verdict (str)
    """
    default_result = {
        "condition_type": "used_good",
        "condition_score": 90,
        "defects": [],
        "estimated_resell_price": int(price * 1.3),
        "expected_profit": int(price * 0.3),
        "net_profit": int(price * 0.25),
        "bargain_price": int(price * 0.8),
        "liquidity": "normal",
        "urgency": "medium",
        "market_saturation": "medium",
        "seller_risk": "low",
        "seller_risk_reason": "",
        "seasonality": "normal",
        "confidence": "medium",
        "product_name_corrected": title,
        "verdict": "Анализ ИИ недоступен (не задан API ключ DEEPSEEK_API_KEY или GEMINI_API_KEY)."
    }

    if settings.deepseek_api_key:
        result = await _analyze_with_deepseek(title, description, price)
        if result:
            return result

    if settings.gemini_api_key:
        result = await _analyze_with_gemini(title, description, price)
        if result:
            return result

    return default_result
