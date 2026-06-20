"""Debug dashboard 500 error."""
import sys
sys.path.insert(0, ".")

# Check template syntax
tpl_path = "app/web/templates/index.html"
with open(tpl_path, "r", encoding="utf-8") as f:
    content = f.read()

# Count Jinja2 blocks
import re
opens_if = len(re.findall(r"{%\s*if\s", content))
closes_if = len(re.findall(r"{%\s*endif\s*%}", content))
opens_for = len(re.findall(r"{%\s*for\s", content))
closes_for = len(re.findall(r"{%\s*endfor\s*%}", content))

print(f"Template: {len(content)} bytes")
print(f"if: {opens_if} opens, {closes_if} closes")
print(f"for: {opens_for} opens, {closes_for} closes")

# Test dashboard route
from app.web.web_server import app
from starlette.testclient import TestClient

client = TestClient(app)
try:
    r = client.get("/")
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(f"Error: {r.text[:500]}")
except Exception as e:
    print(f"Exception: {e}")
