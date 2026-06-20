import os
import json
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.storage.database import SessionLocal
from app.storage.models import Ad, UserFeedback, CategoryStats
from app.storage.repositories import FeedbackRepository, CategoryStatsRepository
from app.services.learning import get_pause_state, set_pause_state, load_settings, apply_feedback_learning
from app.services.monitor import load_watchlist
from app.olx.chat_service import OLXChatService

from fastapi.middleware.cors import CORSMiddleware
from app.web.routes_crawler import router as crawler_router
from app.web.routes_search import router as search_router

from contextlib import asynccontextmanager
import sys
import asyncio
import random
from config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.utils.logger import setup_logger, logger
    from app.storage.database import init_sync_db
    from app.bot.telegram_bot import start_bot, bot
    from app.services.monitor import run_monitoring_cycle, load_watchlist
    from app.storage.models import Ad
    from app.storage.database import SyncSession
    from app.services.notifier import send_ad_notification

    setup_logger()
    logger.info("Resell Radar Ukraine v2.1 — Lifespan Initialized")

    try:
        init_sync_db()
        logger.info("Database OK")
    except Exception as e:
        logger.critical("Database init failed: {}", e)
        sys.exit(1)

    async def flush_pending_notifications():
        """Send any pending 'ready' ads that weren't sent yet."""
        while True:
            await asyncio.sleep(30)
            try:
                # We will keep this sync query wrapped in to_thread if needed,
                # but since it runs in a background task periodically, it's fine for now.
                session = SyncSession()
                try:
                    pending = session.query(Ad).filter(
                        Ad.status == "ready",
                        Ad.sent_to_telegram == False,
                    ).limit(5).all()
                    watchlist = load_watchlist()
                    watch_map = {w["id"]: w for w in watchlist}
                    for ad in pending:
                        item = watch_map.get(ad.watch_item_id, {})
                        try:
                            await send_ad_notification(bot, settings.telegram_chat_id, ad, item)
                            ad.sent_to_telegram = True
                            logger.info("Pending notification sent: %s", ad.title[:50])
                        except Exception:
                            break  # bot not ready yet
                    session.commit()
                finally:
                    session.close()
            except Exception as e:
                logger.debug("Flush pending check: %s", e)

    async def monitor_scheduler(bot_instance):
        logger.info("Monitor scheduler started.")
        await asyncio.sleep(5)
        while True:
            try:
                await run_monitoring_cycle(bot_instance)
            except Exception as e:
                logger.critical("Monitor cycle error: {}", e)
            sleep_time = random.randint(
                settings.check_interval_min_seconds,
                settings.check_interval_max_seconds,
            )
            logger.info("Sleeping {}s", sleep_time)
            await asyncio.sleep(sleep_time)

    tasks = [
        asyncio.create_task(start_bot()),
        asyncio.create_task(flush_pending_notifications()),
    ]
    if not settings.disable_internal_scheduler:
        tasks.append(asyncio.create_task(monitor_scheduler(bot)))
    else:
        logger.info("Internal scheduler is disabled (orchestration handled by Celery).")

    yield

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

app = FastAPI(title="Resell Radar Ukraine Dashboard", lifespan=lifespan)
app.include_router(crawler_router)
app.include_router(search_router)

# Enable CORS for cross-origin console scripts from olx.ua
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup Jinja2 templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Dependency to get db session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health")
async def health():
    from config import settings as cfg
    return {"status": "ok", "version": "2.0.0", "database": str(cfg.database_url_sync[:30])}


class StatusUpdatePayload(BaseModel):
    status: str
    buy_price: int | None = None
    sell_price: int | None = None

class PausePayload(BaseModel):
    paused: bool

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    # 1. System state
    is_paused = get_pause_state()
    
    # 2. Basic counts
    total_found = db.query(Ad).count()
    total_sent = db.query(Ad).filter(Ad.sent_to_telegram == True).count()
    bought_count = db.query(UserFeedback).filter(UserFeedback.action == "bought").count()
    sold_count = db.query(UserFeedback).filter(UserFeedback.action == "sold").count()
    trash_count = db.query(UserFeedback).filter(UserFeedback.action == "trash").count()
    
    # 3. Financial summary
    financials = FeedbackRepository.get_financial_summary(db)
    
    # 4. Watchlist
    watchlist = load_watchlist()
    settings_data = load_settings()
    threshold_modifiers = settings_data.get("watchlist_threshold_modifiers", {})
    
    for item in watchlist:
        item["threshold_modifier"] = threshold_modifiers.get(item["id"], 0)
        # Calculate the effective threshold
        from config import settings as global_settings
        base_threshold = global_settings.deal_score_threshold
        item["effective_threshold"] = base_threshold + item["threshold_modifier"]
    
    # 5. Recent Ads
    recent_ads = db.query(Ad).order_by(desc(Ad.created_at)).limit(100).all()
    
    from config import settings as global_settings
    has_token = bool(global_settings.olx_bearer_token)
    
    context = {
        "request": request,
        "is_paused": is_paused,
        "total_found": total_found,
        "total_sent": total_sent,
        "bought_count": bought_count,
        "sold_count": sold_count,
        "trash_count": trash_count,
        "total_profit": financials["total_profit"],
        "avg_roi": financials["avg_roi"],  # already percentage in DB
        "best_category": financials["best_category"],
        "best_item": financials["best_item"],
        "watchlist": watchlist,
        "recent_ads": recent_ads,
        "has_token": has_token,
    }
    try:
        return templates.TemplateResponse(request, "index.html", context)
    except Exception:
        return templates.TemplateResponse("index.html", context)

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    # Category stats
    cat_stats = db.query(CategoryStats).order_by(desc(CategoryStats.total_profit)).all()
    categories_data = []
    for s in cat_stats:
        categories_data.append({
            "category": s.category,
            "profit": s.total_profit,
            "avg_roi": s.avg_roi,
            "sent": s.total_sent,
            "bought": s.total_bought,
            "sold": s.total_sold,
            "trash": s.total_trash
        })
        
    # Actions distribution
    actions = {
        "bought": db.query(UserFeedback).filter(UserFeedback.action == "bought").count(),
        "sold": db.query(UserFeedback).filter(UserFeedback.action == "sold").count(),
        "trash": db.query(UserFeedback).filter(UserFeedback.action == "trash").count(),
        "interesting": db.query(UserFeedback).filter(UserFeedback.action == "interesting").count()
    }
    
    # Financial metrics
    financials = FeedbackRepository.get_financial_summary(db)
    
    return JSONResponse(content={
        "categories": categories_data,
        "actions": actions,
        "total_profit": financials["total_profit"],
        "avg_roi": financials["avg_roi"],
        "best_category": financials["best_category"],
        "best_item": financials["best_item"]
    })

@app.get("/api/ai/accuracy")
def api_ai_accuracy():
    from app.services.ai_learning import get_accuracy_stats, get_accuracy_by_category
    from app.storage.database import SessionLocal
    db = SessionLocal()
    try:
        stats = get_accuracy_stats(db)
        by_cat = get_accuracy_by_category(db)
        return {"stats": stats, "by_category": by_cat}
    finally:
        db.close()


@app.post("/api/pause")
def toggle_pause(payload: PausePayload):
    set_pause_state(payload.paused)
    return {"status": "ok", "is_paused": payload.paused}

@app.post("/api/ads/{ad_id}/status")
def update_ad_status(ad_id: int, payload: StatusUpdatePayload, db: Session = Depends(get_db)):
    ad = db.query(Ad).filter(Ad.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Ad not found")
        
    status = payload.status
    category = ad.category
    watch_item_id = ad.watch_item_id
    
    if status == "interesting":
        ad.status = "interesting"
        feedback = UserFeedback(ad_id=ad_id, action="interesting")
        db.add(feedback)
        apply_feedback_learning(category, watch_item_id, "interesting")
        
    elif status == "trash":
        ad.status = "trash"
        feedback = UserFeedback(ad_id=ad_id, action="trash")
        db.add(feedback)
        CategoryStatsRepository.increment_stats(db, category, trash=1)
        apply_feedback_learning(category, watch_item_id, "trash")
        
    elif status == "bought":
        ad.status = "bought"
        feedback = UserFeedback(ad_id=ad_id, action="bought")
        db.add(feedback)
        CategoryStatsRepository.increment_stats(db, category, bought=1)
        apply_feedback_learning(category, watch_item_id, "bought")
        
    elif status == "sold":
        if payload.buy_price is None or payload.sell_price is None:
            raise HTTPException(status_code=400, detail="Buy price and sell price are required for sold status")
            
        buy_price = payload.buy_price
        sell_price = payload.sell_price
        profit = sell_price - buy_price
        roi = (profit / buy_price) * 100.0 if buy_price > 0 else 0.0
        
        ad.status = "sold"
        feedback = UserFeedback(
            ad_id=ad_id,
            action="sold",
            buy_price=buy_price,
            sell_price=sell_price,
            profit=profit,
            roi=roi
        )
        db.add(feedback)
        CategoryStatsRepository.increment_stats(db, category, sold=1, profit=profit)
        apply_feedback_learning(category, watch_item_id, "sold")
        
    else:
        raise HTTPException(status_code=400, detail="Invalid status")
        
    db.commit()
    return {"status": "ok", "new_status": ad.status}


# ── AI Suggest endpoint — auto-fill watchlist form ────────────────────────────

class AISuggestPayload(BaseModel):
    name: str

_AI_SUGGEST_PROMPT = """
Ты — эксперт по украинскому рынку перепродаж (OLX Ukraine).
Пользователь хочет мониторить товар для перепродажи: "{name}"

Твоя задача — заполнить все поля конфига для мониторинга. Ответь СТРОГО в формате JSON без пояснений:

{{
  "id": "<уникальный_id_латиницей_без_пробелов_underscore>",
  "name": "<полное правильное название товара>",
  "category": "<одна из: phones, laptops, gaming, bikes, transport, tools, toys, kids, clothes, other>",
  "olx_category_path": "<путь категории OLX Ukraine, например: elektronika/telefony-i-aksesuary/mobilnye-telefony-i-aksesuary/mobilnye-telefony>",
  "search_query": "<поисковый запрос для URL OLX, латиницей через дефис, например: iphone-13>",
  "keywords": ["<ключевое слово 1>", "<ключевое слово 2 на украинском>"],
  "bad_words": ["<стоп-слово 1>", "<стоп-слово 2>"],
  "max_green_price": <максимальная цена покупки для перепродажи с прибылью, целое число UAH>,
  "normal_price_range_min": <минимальная рыночная цена продажи, целое число UAH>,
  "normal_price_range_max": <максимальная рыночная цена продажи, целое число UAH>,
  "min_profit": <минимальная ожидаемая прибыль UAH>,
  "price_floor": <минимальная цена объявления (15% от normal_price_range_min), чтобы отсеять аксессуары>,
  "reasoning": "<1-2 предложения почему такие цены на украинском рынке>"
}}

ВАЖНО:
- Цены для УКРАИНСКОГО рынка (UAH, 2024-2025 год)
- bad_words должны содержать: дефекты, риски, аксессуары-конкуренты для этого товара
- keywords — варианты написания товара (рус, укр, транслит)
- olx_category_path — реальный путь категории OLX Ukraine (без домена, без /uk/)
- Отвечай ТОЛЬКО валидным JSON
"""

async def _call_deepseek_suggest(name: str) -> dict | None:
    from config import settings as gs
    if not gs.deepseek_api_key:
        return None
    prompt = _AI_SUGGEST_PROMPT.format(name=name)
    headers = {"Authorization": f"Bearer {gs.deepseek_api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "Ты эксперт по украинскому рынку перепродаж. Отвечай только валидным JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 700,
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post("https://api.deepseek.com/chat/completions", json=payload, headers=headers)
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                return json.loads(raw)
    except Exception as e:
        pass
    return None

async def _call_gemini_suggest(name: str) -> dict | None:
    from config import settings as gs
    if not gs.gemini_api_key:
        return None
    prompt = _AI_SUGGEST_PROMPT.format(name=name)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gs.gemini_api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(raw)
    except Exception:
        pass
    return None

@app.post("/api/watchlist/ai-suggest")
async def ai_suggest_watchlist(payload: AISuggestPayload):
    """
    Uses DeepSeek (or Gemini fallback) to auto-fill watchlist form fields
    based on the product name entered by the user.
    """
    name = payload.name.strip()
    if not name or len(name) < 2:
        raise HTTPException(status_code=400, detail="Имя товара слишком короткое")

    # Try DeepSeek first, then Gemini
    result = await _call_deepseek_suggest(name)
    if not result:
        result = await _call_gemini_suggest(name)
    if not result:
        raise HTTPException(status_code=503, detail="Не удалось получить ответ от ИИ. Проверьте DEEPSEEK_API_KEY / GEMINI_API_KEY в .env")

    # Build the proper OLX category URL with price filter
    cat_path = result.get("olx_category_path", "list").strip("/")
    search_q = result.get("search_query", "").strip()
    price_floor = result.get("price_floor", 0)
    
    if search_q:
        search_url = f"https://www.olx.ua/uk/{cat_path}/q-{search_q}/?search%5Bfilter_float_price%3Afrom%5D={int(price_floor)}&search%5Border%5D=created_at%3Adesc"
    else:
        search_url = f"https://www.olx.ua/uk/{cat_path}/?search%5Bfilter_float_price%3Afrom%5D={int(price_floor)}&search%5Border%5D=created_at%3Adesc"

    return {
        "id": result.get("id", ""),
        "name": result.get("name", name),
        "category": result.get("category", "other"),
        "search_url": search_url,
        "keywords": result.get("keywords", []),
        "bad_words": result.get("bad_words", []),
        "max_green_price": result.get("max_green_price", 0),
        "normal_price_range_min": result.get("normal_price_range_min", 0),
        "normal_price_range_max": result.get("normal_price_range_max", 0),
        "min_profit": result.get("min_profit", 500),
        "reasoning": result.get("reasoning", ""),
    }

WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "watchlist.json"
)

class WatchlistItemPayload(BaseModel):
    id: str
    name: str
    category: str
    search_url: str
    keywords: list[str]
    bad_words: list[str]
    max_green_price: int
    normal_price_range: list[int]
    min_profit: int

@app.post("/api/watchlist")
async def add_watchlist_item(payload: WatchlistItemPayload):
    watchlist = load_watchlist()
    
    # Check if id already exists
    if any(item["id"] == payload.id for item in watchlist):
        raise HTTPException(status_code=400, detail=f"Объект с ID '{payload.id}' уже существует!")
        
    new_item = {
        "id": payload.id,
        "name": payload.name,
        "category": payload.category,
        "search_url": payload.search_url,
        "keywords": [k.strip() for k in payload.keywords if k.strip()],
        "bad_words": [b.strip() for b in payload.bad_words if b.strip()],
        "max_green_price": payload.max_green_price,
        "normal_price_range": payload.normal_price_range,
        "min_profit": payload.min_profit
    }
    
    watchlist.append(new_item)
    
    try:
        with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
            json.dump(watchlist, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить watchlist.json: {e}")
        
    return {"status": "ok", "message": "Объект успешно добавлен"}

@app.delete("/api/watchlist/{item_id}")
async def delete_watchlist_item(item_id: str):
    watchlist = load_watchlist()
    
    initial_len = len(watchlist)
    watchlist = [item for item in watchlist if item["id"] != item_id]
    
    if len(watchlist) == initial_len:
        raise HTTPException(status_code=404, detail=f"Объект с ID '{item_id}' не найден в watchlist")
        
    try:
        with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
            json.dump(watchlist, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить watchlist.json: {e}")
        
    return {"status": "ok", "message": "Объект успешно удален"}

class TokenPayload(BaseModel):
    token: str

@app.get("/api/settings/olx_status")
async def get_olx_status():
    from config import settings as global_settings
    token = global_settings.olx_bearer_token
    if not token:
        return {"has_token": False, "is_valid": False, "user_info": None, "token_preview": None}
        
    success, user_info = await OLXChatService.verify_token(token)
    token_preview = f"{token[:10]}...{token[-10:]}" if len(token) > 20 else token
    return {
        "has_token": True,
        "is_valid": success,
        "user_info": user_info if success else f"Ошибка: {user_info}",
        "token_preview": token_preview
    }

@app.post("/api/settings/olx_token")
async def set_olx_token(payload: TokenPayload):
    token = payload.token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
        
    if not token:
        raise HTTPException(status_code=400, detail="Токен не может быть пустым")
        
    success, user_info = await OLXChatService.verify_token(token)
    if not success:
        raise HTTPException(status_code=400, detail=f"Невалидный токен OLX: {user_info}")
        
    saved = OLXChatService.update_token(token)
    if not saved:
        raise HTTPException(status_code=500, detail="Не удалось сохранить токен в .env")
        
    return {"status": "ok", "user_info": user_info}

