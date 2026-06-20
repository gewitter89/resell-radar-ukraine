import os
import httpx
from app.utils.logger import logger
from config import settings


def _get_olx_headers(token: str) -> dict:
    """Returns common browser-like headers for OLX API requests."""
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8",
        "Origin": "https://www.olx.ua",
        "Referer": "https://www.olx.ua/",
    }


class OLXChatService:
    @staticmethod
    async def verify_token(token: str) -> tuple[bool, str]:
        """
        Verifies if the OLX bearer token is valid by calling /api/v1/users/me/.
        Returns (True, "Name/Email") if valid, (False, error_reason) otherwise.
        """
        headers = _get_olx_headers(token)
        url = "https://www.olx.ua/api/v1/users/me/"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        user_info = data.get("name") or data.get("email") or "Авторизован"
                    except Exception:
                        user_info = "Авторизован"
                    return True, user_info
                elif response.status_code == 401:
                    return False, "Неверный или просроченный токен (401 Unauthorized)"
                else:
                    return False, f"Ошибка проверки: HTTP {response.status_code}"
        except UnicodeEncodeError:
            return False, "Токен содержит недопустимые символы (убедитесь, что скопировали только токен)."
        except Exception as e:
            return False, f"Ошибка сети при проверке токена: {e}"

    @staticmethod
    def update_token(token: str) -> bool:
        """
        Updates the OLX token in the live config and persists it to the .env file.
        """
        try:
            settings.olx_bearer_token = token

            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            env_path = os.path.join(base_dir, ".env")

            if not os.path.exists(env_path):
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(f"OLX_BEARER_TOKEN={token}\n")
                return True

            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            token_found = False
            new_lines = []
            for line in lines:
                if line.strip().startswith("OLX_BEARER_TOKEN="):
                    new_lines.append(f"OLX_BEARER_TOKEN={token}\n")
                    token_found = True
                else:
                    new_lines.append(line)

            if not token_found:
                new_lines.append(f"\nOLX_BEARER_TOKEN={token}\n")

            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

            logger.info("Successfully updated OLX_BEARER_TOKEN in .env and config.")
            return True
        except Exception as e:
            logger.error("Failed to update OLX token in .env: {}", e)
            return False

    @staticmethod
    async def send_message(olx_ad_id: str, text: str) -> tuple[bool, str]:
        """
        Sends a message directly to the OLX seller via the OLX API v1.

        Correct 2-step flow:
        1. POST /api/v1/chats/ with {"ad_id": <int>}
           → creates or retrieves a chat thread, returns thread_id in response
        2. POST /api/v1/chats/{thread_id}/messages/ with {"text": <str>}
           → sends the actual message text to the seller
        """
        token = getattr(settings, "olx_bearer_token", None)
        if not token:
            return False, "Токен авторизации OLX (OLX_BEARER_TOKEN) не настроен в .env."

        headers = _get_olx_headers(token)

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                # ── Step 1: Create or retrieve chat thread ──────────────────────
                init_url = "https://www.olx.ua/api/v1/chats/"
                init_payload = {"ad_id": int(olx_ad_id)}

                init_resp = await client.post(init_url, json=init_payload, headers=headers)

                if init_resp.status_code == 401:
                    logger.warning("OLX auth token expired or invalid (401) on chat init.")
                    return False, "Ошибка: Токен авторизации OLX устарел (401). Обновите его командой /token."

                if init_resp.status_code not in [200, 201]:
                    logger.warning(
                        "OLX API chat init returned status {}: {}",
                        init_resp.status_code, init_resp.text[:300]
                    )
                    try:
                        err_data = init_resp.json()
                        err_msg = (
                            err_data.get("error", {}).get("message")
                            or err_data.get("message")
                            or f"HTTP {init_resp.status_code}"
                        )
                    except Exception:
                        err_msg = f"HTTP {init_resp.status_code}"
                    return False, f"Ошибка создания чата OLX: {err_msg}"

                # Extract thread ID — OLX returns it in various locations
                init_data = init_resp.json()
                thread_id = (
                    init_data.get("id")
                    or init_data.get("result", {}).get("id")
                    or init_data.get("data", {}).get("id")
                )

                if not thread_id:
                    logger.warning("Could not extract thread_id from OLX chat response: {}", init_data)
                    return False, "Ошибка: Не удалось получить ID чата от OLX API."

                logger.info(
                    "OLX chat thread obtained. Thread ID: {}, Ad ID: {}", thread_id, olx_ad_id
                )

                # ── Step 2: Send message to the thread ──────────────────────────
                msg_url = f"https://www.olx.ua/api/v1/chats/{thread_id}/messages/"
                msg_payload = {"text": text}

                msg_resp = await client.post(msg_url, json=msg_payload, headers=headers)

                if msg_resp.status_code in [200, 201]:
                    logger.info(
                        "OLX message sent successfully. Thread: {}, Ad: {}", thread_id, olx_ad_id
                    )
                    return True, "Сообщение успешно отправлено продавцу напрямую в чат OLX! ✅"

                elif msg_resp.status_code == 401:
                    return False, "Ошибка: Токен авторизации OLX устарел при отправке сообщения (401)."

                else:
                    logger.warning(
                        "OLX message send returned status {}: {}",
                        msg_resp.status_code, msg_resp.text[:300]
                    )
                    try:
                        err_data = msg_resp.json()
                        err_msg = (
                            err_data.get("error", {}).get("message")
                            or err_data.get("message")
                            or f"HTTP {msg_resp.status_code}"
                        )
                    except Exception:
                        err_msg = f"HTTP {msg_resp.status_code}"
                    return False, f"Ошибка отправки сообщения OLX: {err_msg}"

        except Exception as e:
            logger.error("Failed to send message via OLX API: {}", e)
            return False, f"Ошибка сети при отправке сообщения на OLX: {e}"
