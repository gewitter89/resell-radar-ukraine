"""
Resell Radar Ukraine v2.1 — Production entry point.
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.web.web_server:app", host="0.0.0.0", port=8000, log_level="info")

