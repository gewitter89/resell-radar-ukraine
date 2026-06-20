from app.scoring.text_analyzer import clean_text, find_matches, STRONG_BAD_WORDS

def calculate_risk_score(
    price: float,
    market_median: float,
    title: str = "",
    description: str = "",
    image_url: str | None = None,
    item_bad_words: list[str] = None,
    global_bad_words: list[str] = None,
    watch_item: dict = None,
    ai_defects: list[str] = None
) -> int:
    """
    Computes risk score (0-100) based on listing details and optional AI audits.
    - Strong bad word: +35
    - Normal bad word: +15
    - Price under 40% of market median: +20
    - Missing description: +10
    - Missing photo: +15
    - AI detected defects: +20 per defect
    """
    score = 0
    
    # 1. Text checks (combining title and description)
    text_content = f"{title or ''} {description or ''}"
    cleaned_text = clean_text(text_content)
    
    # Compile list of bad words
    bad_words_pool = set()
    if item_bad_words:
        bad_words_pool.update(item_bad_words)
    if global_bad_words:
        bad_words_pool.update(global_bad_words)
    if watch_item and "bad_words" in watch_item:
        bad_words_pool.update(watch_item["bad_words"])
        
    found = find_matches(cleaned_text, list(bad_words_pool))
    
    strong_found = []
    normal_found = []
    
    for word in found:
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
            
    if strong_found:
        score += 35 * len(set(strong_found))
    if normal_found:
        score += 15 * len(set(normal_found))
        
    # 2. Too low price (scam check)
    if market_median > 0 and price <= market_median * 0.4:
        score += 20
        
    # 3. No description
    desc_clean = description.strip() if description else ""
    if len(desc_clean) < 20:
        score += 10
        
    # 4. No photo
    if not image_url:
        score += 15
        
    # 5. AI detected defects
    if ai_defects:
        score += 20 * len(ai_defects)
        
    return min(100, max(0, score))
