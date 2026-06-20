import json
import httpx
import time

with open("app/data/watchlist.json", "r", encoding="utf-8") as f:
    watchlist = json.load(f)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7,ru;q=0.6"
}

print("Testing watchlist URLs:")
for item in watchlist:
    url = item["search_url"]
    try:
        r = httpx.get(url, headers=headers, follow_redirects=True, timeout=10.0)
        print(f"ID: {item['id']} | Status: {r.status_code} | URL: {url}")
    except Exception as e:
        print(f"ID: {item['id']} | Error: {e} | URL: {url}")
    time.sleep(1.0)
