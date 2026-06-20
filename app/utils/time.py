import re
from datetime import datetime, timedelta

MONTHS_UA = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4,
    "травня": 5, "червня": 6, "липня": 7, "серпня": 8,
    "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12
}

def parse_olx_datetime(date_str: str) -> datetime:
    """
    Parses Ukrainian OLX date representation to standard python datetime.
    Examples:
      - 'Сьогодні о 14:20' -> datetime of today at 14:20
      - 'Вчора о 09:15' -> datetime of yesterday at 09:15
      - '28 травня 2026 р.' -> datetime 28 May 2026
      - '15 квітня' -> datetime 15 April (current year)
      - '2 хв. тому' -> datetime 2 minutes ago
      - '1 год. тому' -> datetime 1 hour ago
    """
    if not date_str:
        return datetime.now()
        
    date_str = date_str.strip().lower()
    now = datetime.now()
    
    # 1. "сьогодні о 14:20" or "сегодня о 14:20"
    if "сьогодні" in date_str or "сегодня" in date_str:
        time_match = re.search(r'(\d{1,2}):(\d{2})', date_str)
        if time_match:
            h, m = map(int, time_match.groups())
            return now.replace(hour=h, minute=m, second=0, microsecond=0)
            
    # 2. "вчора о 09:15" or "вчера о 09:15"
    if "вчора" in date_str or "вчера" in date_str:
        time_match = re.search(r'(\d{1,2}):(\d{2})', date_str)
        if time_match:
            h, m = map(int, time_match.groups())
            yesterday = now - timedelta(days=1)
            return yesterday.replace(hour=h, minute=m, second=0, microsecond=0)
            
    # 3. Relative times
    # "2 хв. тому" (minutes)
    min_match = re.search(r'(\d+)\s*хв', date_str)
    if min_match:
        mins = int(min_match.group(1))
        return now - timedelta(minutes=mins)
        
    # "1 год. тому" (hours)
    hour_match = re.search(r'(\d+)\s*год', date_str)
    if hour_match:
        hours = int(hour_match.group(1))
        return now - timedelta(hours=hours)
        
    # 4. Specific dates like "28 травня 2026"
    for month_name, month_num in MONTHS_UA.items():
        if month_name in date_str:
            day_match = re.search(r'(\d{1,2})', date_str)
            if day_match:
                day = int(day_match.group(1))
                year_match = re.search(r'(\d{4})', date_str)
                year = int(year_match.group(1)) if year_match else now.year
                try:
                    return datetime(year=year, month=month_num, day=day)
                except ValueError:
                    pass
                    
    return now
