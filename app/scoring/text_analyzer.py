import os
import json
from app.utils.text import find_matches, clean_text
from app.utils.logger import logger

STRONG_BAD_WORDS = {
    "icloud", "не включается", "на запчасти", "не включається", "на запчастини",
    "не работает", "не працює", "бан", "сгорел", "згорів", "заблокирован", "заблокований"
}

def load_global_bad_words() -> list[str]:
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bad_words.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error("Failed to load global bad words: {}", e)
    return []

def analyze_text(text: str, watchlist_bad_words: list[str] = None) -> dict:
    """
    Analyzes listing text for risk-related words.
    Returns details on found bad words, classifying them into strong and normal.
    """
    if not text:
        return {
            "found_bad_words": [],
            "strong_bad_words": [],
            "normal_bad_words": [],
            "has_bad_words": False
        }
        
    cleaned_text = clean_text(text)
    
    # Load global and merge with item-specific bad words
    bad_words_pool = set(load_global_bad_words())
    if watchlist_bad_words:
        bad_words_pool.update(watchlist_bad_words)
        
    found = find_matches(cleaned_text, list(bad_words_pool))
    
    strong_found = []
    normal_found = []
    
    for word in found:
        # If the word or a part of it matches our strong list
        word_clean = clean_text(word)
        is_strong = False
        for s_word in STRONG_BAD_WORDS:
            if s_word in word_clean or word_clean in s_word:
                is_strong = True
                break
        if is_strong:
            strong_found.append(word)
        else:
            normal_found.append(word)
            
    return {
        "found_bad_words": found,
        "strong_bad_words": strong_found,
        "normal_bad_words": normal_found,
        "has_bad_words": len(found) > 0
    }
