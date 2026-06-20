# Resell Radar Ukraine — Полный анализ и архитектура v2.0

> Дата: 2026-06-20
> Источники: GitHub (15+ репозиториев), Reddit (r/flipping, r/webscraping, r/Python, r/AiAutomations, r/passive_income), Hacker News, Dev.to, документация технологий

---

## 1. ТЕКУЩЕЕ СОСТОЯНИЕ (v1.0) — что уже работает

### 1.1 Telegram Bot (aiogram 3.x) — ПОЛНОСТЬЮ РАБОЧИЙ
- `/start`, `/help`, `/stats`, `/profit`, `/top`, `/watchlist`, `/pause`, `/resume`, `/token`
- Инлайн-кнопки: Купил, Интересно, Мусор, Продал, Шаблон, Написать на OLX
- FSM для ввода цен покупки/продажи
- Отправка сообщений через OLX API (2-step: create chat → send message)

### 1.2 Парсинг OLX — РАБОЧИЙ (но без JS)
- httpx + BeautifulSoup с ротацией User-Agent (5 агентов)
- Прокси через round-robin из proxies.txt + PROXIES env
- Exponential backoff (2s, 4s, 6s), таймаут 12s
- Парсинг ленты: data-cy="l-card" с fallback на data-testid и href-детект
- Парсинг детальной страницы: 7+ селекторов для title, 6+ для price, 4+ для location

### 1.3 Scoring Engine — ПОЛНОСТЬЮ РАБОЧИЙ
- Deal Score (0-100): цена (−35/+25/+15), свежесть (+20/+10), keywords (+15), описание (+10), фото (+10), green price (+10), AI modifier (+10/−20/−40)
- Risk Score (0-100): strong bad words (+35), normal (+15), low price (+20), no desc (+10), no photo (+15), AI defects (+20/defect)
- Market Price: trimmed mean (15% outlier removal), fallback на normal_price_range
- AI Analyzer: DeepSeek → Gemini → rule-based fallback (каскад)

### 1.4 Monitoring Cycle — ПОЛНОСТЬЮ РАБОЧИЙ
- Загрузка watchlist → парсинг ленты → дедупликация (title 85% + description 85%) → AI → scoring → фильтр (deal_score ≥ threshold, risk_score ≤ max, profit ≥ min_profit) → анти-спам (3/cycle) → cooldown (30min) → super-deal bypass (скидка >40%, риск <35%) → отправка в Telegram

### 1.5 Хранилище — РАБОЧЕЕ (но SQLite)
- SQLAlchemy ORM, 4 модели: Ad, UserFeedback, MarketSnapshot, CategoryStats
- Репозитории: CRUD, финансовая аналитика, дедупликация, cooldown

### 1.6 FastAPI Web Dashboard — РАБОЧИЙ
- Главная: статистика, watchlist с threshold modifier, последние 100 объявлений
- /api/stats — категории, действия, финансы
- /api/watchlist — CRUD + AI-suggest через DeepSeek/Gemini
- /api/settings/olx_token — управление токеном OLX
- HTML-шаблон (1972 строки) с Chart.js, тёмная тема

### 1.7 Feedback Learning — РАБОЧИЙ
- trash: +3 к порогу (строже), bought/sold: −3 (мягче), interesting: −1
- Кап: ±15
- Состояние в settings.json

---

## 2. ПРОБЛЕМЫ (из аудита кода + исследования)

### 2.1 Критические

| # | Проблема | Детали |
|---|----------|--------|
| C1 | **SQLite блокирует event loop** | engine синхронный, нет async. При параллельных запросах (мониторинг + веб) будут блокировки. `pool_size=1` в SQLite |
| C2 | **httpx без JS скоро сломается** | OLX внедряет JS-рендеринг. Текущий парсер работает, но каждый апдейт OLX может его сломать |
| C3 | **Нет изоляции сервисов** | Мониторинг, веб-сервер, бот — в одном процессе. Падение любого = всё упало |
| C4 | **numpy 2.0+ dependency** | Импортируется 27MB библиотека ради `np.median` в одной функции |

### 2.2 Средние

| # | Проблема | Детали |
|---|----------|--------|
| M1 | **Нет rate limiting** | Веб-сервер без защиты от DDoS/brute-force |
| M2 | **Нет Alembic миграций** | create_all() при каждом запуске. При изменении схемы нужно вручную удалять БД |
| M3 | **Cooldown не resilient** | При падении процесса cooldown сбрасывается |
| M4 | **Watchlist управляется вручную** | Нет API для добавления через Telegram, только через веб-дашборд или редактирование JSON |

### 2.3 Улучшения (из research)

| # | Идея | Источник |
|---|------|----------|
| R1 | **Token-overlap similarity** вместо exact match для дедупликации | olx_hunter (GitHub) |
| R2 | **Price-drop re-alerts** — повторное уведомление при снижении цены | olx_hunter |
| R3 | **Dynamic category crawling** — обход OLX как граф, а не по URL | sslv-bot |
| R4 | **Notification dedup таблица** — гарантия что объявление не придёт дважды | olx-domria-scraper |
| R5 | **Bi-modal outlier detection** — peer cohort ±100× для mixed выдачи | olx-domria-scraper |
| R6 | **Celery Beat с random interval** — для избежания паттерна | olx_hunter + community |
| R7 | **Local Ollama** — замена API вызовов DeepSeek для частых операций | research |

---

## 3. РЕКОМЕНДУЕМАЯ АРХИТЕКТУРА v2.0

### 3.1 Общая схема

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Compose                           │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │  Nginx    │  │  FastAPI │  │  Celery  │  │  Celery Beat   │  │
│  │  (proxy)  │←→│  (web)   │  │  Worker  │  │  (scheduler)   │  │
│  └──────────┘  └────┬─────┘  └────┬─────┘  └───────┬────────┘   │
│                     │             │                 │            │
│  ┌───────────────────────────────────────────────────────┐      │
│  │                     Redis (broker + cache)            │      │
│  └─────────────┬──────────────────┬──────────────────────┘      │
│                │                  │                              │
│  ┌─────────────▼──────┐  ┌───────▼──────────────┐              │
│  │  PostgreSQL 16     │  │  MinIO (S3)          │              │
│  │  (основная БД)     │  │  (фото, артефакты)   │              │
│  └────────────────────┘  └──────────────────────┘              │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐      │
│  │  Ollama (локальный AI)                                │      │
│  │  ├─ qwen3:14b — текстовый анализ объявлений           │      │
│  │  ├─ llava:7b — Vision анализ фото                     │      │
│  │  └─ nomic-embed-text — эмбеддинги для поиска          │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────┐      │
│  │Telegram  │  │ Playwright   │  │ FlareSolverr          │      │
│  │Bot       │  │ (stealth)    │  │ (Cloudflare bypass)   │      │
│  └──────────┘  └──────────────┘  └──────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Компоненты (с обоснованием из research)

#### Сервис 1: PostgreSQL + async SQLAlchemy
- **Выбор:** `asyncpg` драйвер + `SQLAlchemy 2.0 async` — production standard 2025
- **Почему:** единственный поддерживаемый async Postgres драйвер для Python. 2-3x быстрее синхронного.
- **Конфиг:** pool_size=20, max_overflow=10, expire_on_commit=False

#### Сервис 2: Redis
- **Выбор:** Redis 7-alpine
- **Роль:** Celery broker + result backend + rate limiter + cache
- **Обоснование:** research показал что Celery 5.6.x + Redis — production standard

#### Сервис 3: Celery Worker + Beat
- **Выбор:** Celery 5.6.x с `-P gevent` pool (для async I/O)
- **Почему не asyncio в основном процессе:** отдельный процесс = изоляция + перезапуск без потери данных + масштабирование
- **Паттерн:** `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_max_tasks_per_child=1000`
- **Beat schedule:** crontab для фиксированного времени + random sleep внутри таски (из olx_hunter)

#### Сервис 4: Playwright + playwright-stealth
- **Выбор:** Playwright 1.47+ + playwright-stealth 2.0+ (активно поддерживается, Apr 2026)
- **Почему:** puppeteer-extra-stealth покрывает только 30% детектов. Playwright-stealth + fingerprint consistency — текущий best practice
- **Прокси:** на уровне контекста, а не launch (позволяет ротацию без перезапуска браузера)
- **Подход BrowserBook:** детерминированные скрипты для core, AI для edge cases (popups, layout changes)
- **Cloudflare:** FlareSolverr как fallback

#### Сервис 5: Ollama
- **Модели:**
  - `qwen3:14b` — текстовый анализ (лучшее quality/speed, 8-10GB RAM)
  - `llava:7b` — Vision анализ фото (дефекты, состояние)
  - `nomic-embed-text` — эмбеддинги для поиска дубликатов и похожих товаров
- **Каскад:** Ollama (локально, 0$ ) → DeepSeek API (облачно, $) — только для сложных случаев

#### Сервис 6: MinIO (S3-compatible)
- **Фото:** сохраняем full-size при первом парсинге (нужно для Vision AI)
- **Артефакты:** HTML-слепки страниц (для отладки и повторного парсинга)

#### Сервис 7: FastAPI (переработанный)
- **Lifespan** (не startup/shutdown) — рекомендовано FastAPI 0.93+
- **BackgroundTasks** — только для лёгких операций
- **Rate limiting** — через `slowapi` или middleware

### 3.3 Telegram Bot — что менять
- Текущая структура aiogram 3.x — ✅ **правильная** (комьюнити подтверждает)
- Добавить: inline-режим для быстрого поиска по сохранённым
- Добавить: callback для "цена упала" (price-drop re-alert)
- Оставить: FSM для ввода — правильный паттерн

---

## 4. MAP РОУТИНГ — какие идеи из research реально внедряем

| Идея | Источник | Сложность | Эффект | Внедряем? |
|------|----------|-----------|--------|-----------|
| Token-overlap дедупликация | olx_hunter | Средняя | Высокий | ✅ Да |
| Price-drop re-alerts | olx_hunter | Низкая | Средний | ✅ Да |
| Notification dedup таблица | olx-domria-scraper | Низкая | Высокий | ✅ Да (замена текущей ad-hoc дедупликации) |
| Dynamic category crawling | sslv-bot | Высокая | Средний | ⏸ Потом (не сейчас) |
| Bi-modal outlier detection | olx-domria-scraper | Низкая | Средний | ✅ Да |
| Celery random interval | olx_hunter | Низкая | Низкий | ✅ Да |
| Vision AI анализ фото | Research | Средняя | Высокий | ✅ Да (llava:7b) |
| Локальный Ollama | Research | Средняя | Высокий | ✅ Да (экономия $200-500/мес) |
| Price history charts | olx_hunter | Средняя | Средний | ✅ Да (matplotlib или plotly) |
| Celery Flower мониторинг | Research | Низкая | Средний | ✅ Да |
| Playwright | Research | Средняя | Критический | ✅ Да (замена httpx) |
| FlareSolverr | Research | Низкая | Средний | ✅ Да |
| PostgreSQL | Research | Средняя | Критический | ✅ Да (замена SQLite) |
| MinIO S3 | Research | Средняя | Средний | ✅ Да |
| Multi-platform (Prom, Shafa) | Research | Высокая | Высокий | ⏸ Фаза 2 |

---

## 5. ПЛАН ИМПЛЕМЕНТАЦИИ (4 фазы, 14 дней)

### Фаза 1: Security + Containerization (Дни 1-2)
**Цель:** безопасность, repeatable окружение, PostgreSQL

1. `.gitignore` — добавить .env, __pycache__, *.db, logs/
2. `docker-compose.yml` — PostgreSQL, Redis, MinIO, Ollama
3. `Dockerfile` — Python 3.11-slim с зависимостями
4. Миграция SQLite → PostgreSQL через Alembic
5. Переписать database.py на async SQLAlchemy + asyncpg
6. Переписать main.py на lifespan + Celery таски

### Фаза 2: Anti-Detection Scraper (Дни 3-5)
**Цель:** стабильный парсинг с Playwright

1. Установка Playwright + playwright-stealth
2. OLXBrowser class с антидетектом (stealth + fingerprint + прокси)
3. fetch_listings() — скроллинг ленты, сбор ссылок
4. parse_ad() — детальный парсинг карточки
5. FlareSolverr интеграция для Cloudflare fallback
6. Обёртка: Playwright для JS-сайтов, httpx для статических

### Фаза 3: Celery + Background Tasks (Дни 6-8)
**Цель:** надёжный мониторинг в отдельном процессе

1. Celery worker + beat конфиг
2. Перенос monitoring_cycle в Celery task
3. Таски: scrape_listings, process_ad, send_notification
4. Flower мониторинг
5. Notification dedup таблица в PostgreSQL
6. Price-drop re-alert логика

### Фаза 4: AI + Advanced Features (Дни 9-14)
**Цель:** локальный AI, Vision, рыночные цены

1. Ollama: загрузка qwen3:14b, llava:7b, nomic-embed-text
2. TextAgent — анализ текста через qwen3 (fallback DeepSeek)
3. VisionAgent — анализ фото через llava (дефекты, состояние)
4. market_price — парсинг Hotline/Rozetka для реальных цен
5. Embedding similarity — замена SequenceMatcher на векторный поиск
6. Веб-дашборд: history charts, profit analytics, price-drop alerts
7. Price-drop re-alerts в Telegram с кнопками

---

## 6. ТЕХНОЛОГИЧЕСКИЙ СТЭК v2.0 (итоговый)

| Компонент | v1.0 (сейчас) | v2.0 (цель) | Причина |
|-----------|---------------|-------------|---------|
| **Язык** | Python 3.11 | Python 3.11+ | Без изменений |
| **БД** | SQLite | PostgreSQL 16 + asyncpg | Конкурентность, reliability |
| **ORM** | SQLAlchemy sync | SQLAlchemy 2.0 async | Async ecosystem |
| **Брокер** | — | Redis 7 | Celery broker |
| **Очереди** | asyncio gather | Celery 5.6 + Beat | Изоляция, reliability |
| **Парсинг** | httpx + BS4 | Playwright + stealth + httpx | Anti-detection |
| **Cloudflare** | — | FlareSolverr | Обход защиты |
| **Фото** | — | MinIO (S3) | Хранение для Vision AI |
| **AI текст** | DeepSeek API | Ollama qwen3:14b (primary) + DeepSeek (fallback) | $0/мес локально |
| **AI vision** | — | Ollama llava:7b | Анализ дефектов |
| **Эмбеддинги** | SequenceMatcher | Ollama nomic-embed-text | Векторный поиск |
| **Мониторинг** | — | Celery Flower | Визуализация очередей |
| **Миграции** | create_all() | Alembic | Version control схемы |
| **Контейнеры** | — | Docker Compose | Repeatable deploy |
| **Веб-сервер** | FastAPI sync | FastAPI async | Lifespan, DI |
| **Telegram** | aiogram 3.x | aiogram 3.x | ✅ Без изменений |
| **Логи** | loguru | loguru | ✅ Без изменений |

---

## 7. КЛЮЧЕВЫЕ ИНСАЙТЫ ИЗ RESEARCH

### Что community говорит про OLX scraping:
1. "OLX moving toward Cloudflare + login walls" — нужен Playwright + прокси, httpx скоро умрёт
2. "Пассивный доход реален" — r/passive_income: $8/мес сервер → $88/мес доход от 32 подписчиков по $3
3. "Deterministic scripts > AI agents" — BrowserBook (YC F24): AI для edge cases, скрипты для core
4. "Token trick" — агенты не должны иметь длинных диалогов. Один focused prompt → parse → act → done
5. "State management > agent frameworks" — r/AiAutomations: ретраи, идемпотентность, rate limits, dead-letter paths

### Кого копировать:
- **olx-domria-scraper** — самая production-ready архитектура (Django + Celery + Playwright + Docker)
- **olx_hunter** — лучший analytical approach (token-overlap + rolling average + price-drop re-alerts)
- **sslv-bot** — best aiogram 3 architecture reference
- **BrowserBook thesis** — детерминированные скрипты для стабильности
