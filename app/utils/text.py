import re
from difflib import SequenceMatcher

def clean_text(text: str) -> str:
    """
    Cleans and normalizes text for keyword matching.
    """
    if not text:
        return ""
    text = text.lower()
    # Normalize whitespaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def contains_any(text: str, words: list[str]) -> bool:
    """
    Checks if normalized text contains any of the words (as substrings).
    """
    cleaned = clean_text(text)
    for word in words:
        if clean_text(word) in cleaned:
            return True
    return False

def find_matches(text: str, words: list[str]) -> list[str]:
    """
    Returns the list of words that were found in the text.
    """
    cleaned = clean_text(text)
    matched = []
    for word in words:
        cleaned_word = clean_text(word)
        if cleaned_word and cleaned_word in cleaned:
            matched.append(word)
    return matched

def get_similarity_ratio(str1: str, str2: str) -> float:
    """
    Returns similarity ratio between two strings (0.0 to 1.0).
    """
    if not str1 or not str2:
        return 0.0
    return SequenceMatcher(None, clean_text(str1), clean_text(str2)).ratio()
