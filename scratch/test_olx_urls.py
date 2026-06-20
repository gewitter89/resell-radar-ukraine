import httpx

url = "https://www.olx.ua/uk/detskiy-mir/q-maxi-cosi/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7,ru;q=0.6"
}

try:
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=10.0)
    print(f"Status: {r.status_code} | URL: {url} | Final URL: {r.url}")
except Exception as e:
    print(f"Error: {e} | URL: {url}")
