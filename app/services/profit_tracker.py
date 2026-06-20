from app.storage.database import db_session
from app.storage.repositories import AdRepository, FeedbackRepository, CategoryStatsRepository
from app.utils.money import format_price

def get_stats_text() -> str:
    """
    Formulates a report containing bot operation metrics.
    """
    with db_session() as session:
        total_found = AdRepository.get_total_found_count(session)
        total_sent = AdRepository.get_total_sent_count(session)
        bought = FeedbackRepository.get_action_count(session, "bought")
        sold = FeedbackRepository.get_action_count(session, "sold")
        trash = FeedbackRepository.get_action_count(session, "trash")
        
    return (
        "📊 *Статистика Resell Radar Ukraine*\n\n"
        f"🔍 Всего найдено объявлений: {total_found}\n"
        f"📩 Рекомендовано (отправлено): {total_sent}\n"
        f"✅ Куплено (активные): {bought}\n"
        f"💰 Успешно продано: {sold}\n"
        f"🗑 Помечено как мусор: {trash}"
    )

def get_profit_text() -> str:
    """
    Formulates a financial report on total profit and ROIs.
    """
    with db_session() as session:
        summary = FeedbackRepository.get_financial_summary(session)
        
    total_profit_str = format_price(summary["total_profit"])
    avg_roi = summary["avg_roi"]
    best_cat = summary["best_category"]
    best_item = summary["best_item"]
    
    return (
        "💵 *Финансовый отчет перепродаж*\n\n"
        f"💰 Общая чистая прибыль: *{total_profit_str}*\n"
        f"📈 Средний ROI: *{avg_roi:.2f}%*\n"
        f"🗂 Самая прибыльная категория: *{best_cat.capitalize()}*\n"
        f"🏷 Лучший товар для флиппинга: *{best_item.upper()}*"
    )

def get_top_categories_text() -> str:
    """
    Lists categories ordered by accumulated net profit.
    Reads all ORM data within the session to avoid DetachedInstanceError.
    """
    with db_session() as session:
        stats_orm = CategoryStatsRepository.get_all_ordered_by_profit(session)
        # Serialize all data to plain dicts BEFORE session closes
        stats = [
            {
                "category": s.category,
                "total_profit": s.total_profit or 0,
                "avg_roi": s.avg_roi or 0.0,
                "total_sold": s.total_sold or 0,
                "total_bought": s.total_bought or 0,
            }
            for s in stats_orm
        ]
        
    if not stats:
        return "🗂 *Рейтинг категорий по прибыли*\n\nДанных по продажам пока нет."
        
    lines = ["🗂 *Рейтинг категорий по прибыли:*", ""]
    for i, s in enumerate(stats, 1):
        profit_str = format_price(s["total_profit"])
        lines.append(
            f"{i}. *{s['category'].capitalize()}*:\n"
            f"   • Прибыль: {profit_str}\n"
            f"   • Средний ROI: {s['avg_roi']:.2f}%\n"
            f"   • Сделок: {s['total_sold']} продано / {s['total_bought']} куплено"
        )
        
    return "\n".join(lines)
