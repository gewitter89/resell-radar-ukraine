"""Test search API - v2."""
import json
import urllib.request

url = "http://127.0.0.1:8000/api/search?q=iphone+12&max_results=2"
try:
    r = urllib.request.urlopen(url, timeout=90)
    d = json.loads(r.read())
    print(f"Results: {d['count']}")
    if d["results"]:
        for i, item in enumerate(d["results"], 1):
            print(f"\n--- Result {i} ---")
            print(f"Title: {item['title'][:70]}")
            print(f"Price: {item['price']} UAH")
            print(f"Profit: {item['profit_pct']}% ({item['profit']} UAH)")
            print(f"Deal: {item['deal_score']}/100 | Risk: {item['risk_score']}/100")
            ai = item["ai"]
            print(f"AI: {ai['condition']} | Liq: {ai['liquidity']} | Conf: {ai['confidence']}")
            print(f"Resell: ~{ai['resell_price']} UAH | Net: ~{ai['net_profit']} UAH")
            print(f"Bargain from: {ai['bargain']} UAH")
            print(f"Verdict: {ai['verdict'][:150]}")
    else:
        print("No results found")
except Exception as e:
    print(f"ERROR: {e}")
