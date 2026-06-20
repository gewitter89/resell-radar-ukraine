"""Get Telegram bot username."""
import sys
sys.path.insert(0, ".")
import httpx
from config import settings

r = httpx.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe")
if r.status_code == 200:
    data = r.json()
    bot = data["result"]
    print(f"Username: @{bot['username']}")
    print(f"Name: {bot['first_name']}")
else:
    print(f"Error: {r.text}")
