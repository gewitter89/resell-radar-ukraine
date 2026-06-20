"""Test search API."""
import json, urllib.request

url = "http://127.0.0.1:8000/api/search?q=iphone+12&max_results=2"
try:
    r = urllib.request.urlopen(url, timeout=90)
    d = json.loads(r.read())
    print(f"Results: {d['count']}")
    for item in d['results']:
        print(f"  - {item['title'][:60]}")
        print(f"    Price: {item['price']} UAH, Profit: {item['profit_pct']}%")
        print(f"    Deal: {item['deal_score']}/100, Risk: {item['risk_score']}/100")
        print(f"    AI: {item['ai']['condition']}, {item['ai']['liquidity']}, {item['ai']['confidence']}")
        print(f"    Verdict: {item['ai']['verdict'][:100]}")
except Exception as e:
    print(f"ERROR: {e}")
