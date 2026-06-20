import sys
import os
import httpx

# Add project root to system path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from config import settings

def get_telegram_chat_id():
    token = settings.telegram_bot_token
    print(f"Checking updates for Telegram Bot token: {token}")
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    
    try:
        response = httpx.get(url, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            results = data.get("result", [])
            
            if not results:
                print("❌ No messages found yet. Please send /start or any message to your bot in Telegram first, then run this again!")
                return
                
            # Grab the last message
            last_update = results[-1]
            message = last_update.get("message", {})
            chat = message.get("chat", {})
            chat_id = chat.get("id")
            first_name = chat.get("first_name", "")
            username = chat.get("username", "")
            
            if chat_id:
                print(f"✅ Success! Found chat ID: {chat_id} (User: {first_name} / @{username})")
                
                # Automatically update .env file
                env_path = os.path.join(project_root, ".env")
                if os.path.exists(env_path):
                    with open(env_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        
                    new_lines = []
                    updated = False
                    for line in lines:
                        if line.startswith("TELEGRAM_CHAT_ID="):
                            new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
                            updated = True
                        else:
                            new_lines.append(line)
                            
                    if not updated:
                        new_lines.append(f"\nTELEGRAM_CHAT_ID={chat_id}\n")
                        
                    with open(env_path, "w", encoding="utf-8") as f:
                        f.writelines(new_lines)
                        
                    print(f"✅ Automatically updated TELEGRAM_CHAT_ID in {env_path}!")
                else:
                    print(f"⚠️ .env file not found at {env_path}, please set TELEGRAM_CHAT_ID={chat_id} manually.")
            else:
                print("❌ Could not extract chat ID from the latest message.")
        else:
            print(f"❌ Telegram API returned error code {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Failed to fetch updates: {e}")

if __name__ == "__main__":
    get_telegram_chat_id()
