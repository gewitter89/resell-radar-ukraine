import requests

endpoints = [
    "https://www.olx.ua/api/v1/users/me/chats/",
    "https://www.olx.ua/api/v1/users/me/chats",
    "https://www.olx.ua/api/v1/threads/",
    "https://www.olx.ua/api/v2/threads/",
    "https://api.olx.ua/v1/threads/",
    "https://api.olx.ua/v2/threads/",
    "https://api.olx.ua/v2/threads",
    "https://www.olx.ua/api/v1/users/me/threads/",
    "https://api.olx.ua/api/v1/users/me/threads/",
    "https://www.olx.ua/api/v1/messages/",
    "https://api.olx.ua/api/v1/messages/",
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

print("=== Testing OLX Chat Endpoints ===")
for url in endpoints:
    try:
        r = requests.get(url, headers=headers, timeout=5)
        print(f"URL: {url} => Status: {r.status_code}")
    except Exception as e:
        print(f"URL: {url} => Error: {e}")
