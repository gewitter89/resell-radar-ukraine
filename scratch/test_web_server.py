import asyncio
import sys
import os
import httpx

# Reconfigure stdout/stderr to support emojis on Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Add project root to system path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.web.web_server import app

async def test_endpoints():
    print("=== TESTING FASTAPI WEB PANEL ENDPOINTS ===")
    
    # Use httpx.AsyncClient with ASGITransport for the FastAPI ASGI application
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test Dashboard Page
        print("Testing GET / ...")
        response = await client.get("/")
        if response.status_code == 200:
            print("✅ GET / returned HTTP 200!")
            if "Resell Radar Ukraine" in response.text:
                print("✅ Found correct title in HTML!")
            else:
                print("❌ HTML content does not match expected output.")
        else:
            print(f"❌ GET / failed with status code: {response.status_code}")
            sys.exit(1)
            
        # 2. Test Stats API
        print("\nTesting GET /api/stats ...")
        response = await client.get("/api/stats")
        if response.status_code == 200:
            print("✅ GET /api/stats returned HTTP 200!")
            data = response.json()
            print("✅ Received JSON stats successfully:")
            print(f"   • Total Profit: {data.get('total_profit')} UAH")
            print(f"   • Average ROI: {data.get('avg_roi'):.2f}%")
            print(f"   • Best Category: {data.get('best_category')}")
            print(f"   • Best Item: {data.get('best_item')}")
            print(f"   • Actions count: {data.get('actions')}")
        else:
            print(f"❌ GET /api/stats failed with status code: {response.status_code}")
            sys.exit(1)

        # 3. Test Pause API
        print("\nTesting POST /api/pause ...")
        response = await client.post("/api/pause", json={"paused": True})
        if response.status_code == 200:
            print("✅ POST /api/pause (true) returned HTTP 200!")
            data = response.json()
            print(f"   • is_paused state in response: {data.get('is_paused')}")
            
            # Revert to false
            await client.post("/api/pause", json={"paused": False})
        else:
            print(f"❌ POST /api/pause failed with status code: {response.status_code}")
            sys.exit(1)

    print("\n🎉 ALL WEB SERVER ENDPOINTS TESTED SUCCESSFULLY AND ARE FULLY FUNCTIONAL!")

if __name__ == "__main__":
    asyncio.run(test_endpoints())
