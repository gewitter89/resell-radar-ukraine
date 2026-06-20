import re

def clean_price(price_str: str) -> int:
    """
    Extracts numerical price from OLX price text (e.g., '6 500 грн.', '12 000 грн.').
    Returns 0 if no digits are found (e.g. 'Договірна', 'Безкоштовно').
    """
    if not price_str:
        return 0
    # Remove any spacing
    cleaned = price_str.replace(" ", "").replace("\xa0", "")
    # Find numbers
    match = re.search(r'\d+', cleaned)
    if match:
        # Get all numbers before any non-digit chars in case of decimals
        digits = re.findall(r'\d+', cleaned)
        return int("".join(digits))
    return 0

def format_price(amount: float) -> str:
    """
    Formats integers into human-readable Hryvnia strings (e.g., 6500 -> '6 500 грн').
    """
    try:
        val = int(amount)
        return f"{val:,}".replace(",", " ") + " грн"
    except (ValueError, TypeError):
        return "0 грн"
