import os
import json
from app.utils.logger import logger

SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "settings.json"
)

def load_settings() -> dict:
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load settings.json: {}", e)
    return {"is_paused": False, "category_modifiers": {}, "watchlist_threshold_modifiers": {}}

def save_settings(settings: dict):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("Failed to save settings.json: {}", e)

def apply_feedback_learning(category: str, watch_item_id: str, action: str):
    """
    Adjusts threshold modifiers in settings.json based on user clicks.
    - 'trash': increments threshold modifier (make bot stricter, +3)
    - 'bought' / 'sold': decrements threshold modifier (make bot more permissive, -3)
    - 'interesting': decrements threshold modifier slightly (-1)
    """
    settings = load_settings()
    
    threshold_mods = settings.setdefault("watchlist_threshold_modifiers", {})
    current_mod = threshold_mods.get(watch_item_id, 0)
    
    if action == "super_deal":
        new_mod = current_mod - 5  # strong signal: lower threshold
    elif action == "trash":
        new_mod = current_mod + 3
    elif action in ("bought", "sold"):
        new_mod = current_mod - 3
    elif action == "interesting":
        new_mod = current_mod - 1
    else:
        return
        
    # Cap modifiers between -15 and +15
    new_mod = max(-15, min(15, new_mod))
    threshold_mods[watch_item_id] = new_mod
    
    logger.info(
        "Applied feedback for item '{}'. Action: '{}'. Mod: {} -> {}",
        watch_item_id, action, current_mod, new_mod
    )
    save_settings(settings)

def get_deal_threshold_modifier(watch_item_id: str) -> int:
    settings = load_settings()
    return settings.get("watchlist_threshold_modifiers", {}).get(watch_item_id, 0)

def set_pause_state(paused: bool):
    settings = load_settings()
    settings["is_paused"] = paused
    save_settings(settings)

def get_pause_state() -> bool:
    settings = load_settings()
    return settings.get("is_paused", False)
