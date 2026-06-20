from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, parse_qsl

def ensure_date_sorting(url: str) -> str:
    """
    Guarantees that the OLX search URL contains the order parameter
    for sorting listings by creation date (newest first).
    """
    if not url:
        return url
        
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    
    # Standard OLX parameter for date sorting
    query["search[order]"] = ["created_at:desc"]
    
    new_query = urlencode(query, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))

def get_page_url(url: str, page: int) -> str:
    """
    Appends or replaces the page query parameter in the search URL.
    """
    if page <= 1:
        return url
        
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["page"] = [str(page)]
    
    new_query = urlencode(query, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))

def clean_and_build_url(base_url: str, page: int = 1) -> str:
    """
    Cleans search URL, ensures order is created_at:desc, and adds page query parameter if page > 1.
    """
    url = ensure_date_sorting(base_url)
    if page > 1:
        url = get_page_url(url, page)
    return url
