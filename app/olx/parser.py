import re
import hashlib
from bs4 import BeautifulSoup
from app.olx.models import RawListing, ListingDetails, ScrapedAdDetails
from app.utils.money import clean_price
from app.utils.time import parse_olx_datetime
from app.utils.logger import logger

def extract_olx_id(url: str) -> str:
    """
    Extracts the unique ID from an OLX listing URL.
    """
    match = re.search(r'-ID([a-zA-Z0-9]+)\.html', url)
    if match:
        return match.group(1)
    
    match_digits = re.search(r'-(\d+)\.html', url)
    if match_digits:
        return match_digits.group(1)
        
    match_query = re.search(r'ID([a-zA-Z0-9]+)', url)
    if match_query:
        return match_query.group(1)

    return hashlib.md5(url.encode("utf-8")).hexdigest()[:10]

def parse_listings(html_content: str) -> list[RawListing]:
    """
    Parses listing cards from search result page. Required by verify_app.py.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    ads = []
    
    cards = soup.find_all("div", {"data-cy": "l-card"})
    if not cards:
        cards = soup.find_all("div", {"data-testid": "l-card"})
        
    if not cards:
        anchors = soup.find_all("a", href=True)
        seen_hrefs = set()
        for a in anchors:
            href = a["href"]
            if "/obyavlenie/" in href or "/d/uk/obyavlenie/" in href:
                if href.startswith("/"):
                    href = "https://www.olx.ua" + href
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                card = a.find_parent("div")
                if card:
                    cards.append(card)
        cards = list(dict.fromkeys(cards))

    for card in cards:
        try:
            a_tag = card.find("a", href=True)
            if not a_tag:
                continue
            href = a_tag["href"]
            url = "https://www.olx.ua" + href if href.startswith("/") else href
            olx_id = extract_olx_id(url)
            
            # Title
            title_tag = card.find(["h4", "h5", "h6"])
            if not title_tag:
                title_tag = card.find(class_=re.compile("title|header", re.I))
            title = title_tag.get_text().strip() if title_tag else "No Title"
            
            # Price
            price_tag = card.find(attrs={"data-testid": "ad-price"})
            if not price_tag:
                price_tag = card.find(class_=re.compile("price|css-1dp558c|css-10b0zqi", re.I))
            price_str = price_tag.get_text().strip() if price_tag else "0"
            price = clean_price(price_str)
            
            # Image URL
            image_url = None
            img_tag = card.find("img")
            if img_tag and img_tag.get("src"):
                image_url = img_tag["src"]
            
            # Location and Time
            loc_date_tag = card.find(attrs={"data-testid": "location-date"})
            if not loc_date_tag:
                loc_date_tag = card.find(class_=re.compile("location|date", re.I))
            loc_date_str = loc_date_tag.get_text().strip() if loc_date_tag else ""
            
            location = None
            date_str = None
            if loc_date_str:
                if " - " in loc_date_str:
                    parts = loc_date_str.split(" - ", 1)
                    location = parts[0].strip()
                    date_str = parts[1].strip()
                else:
                    location = loc_date_str
            
            ads.append(RawListing(
                olx_id=olx_id,
                title=title,
                price=float(price),
                url=url,
                location=location,
                image_url=image_url,
                published_date_str=date_str
            ))
        except Exception as e:
            logger.error("Failed to parse card: {}", e)
            
    return ads

def parse_listings_page(html_content: str) -> list[RawListing]:
    """
    Alias for monitor loop.
    """
    return parse_listings(html_content)

def parse_details(html_content: str) -> ListingDetails:
    """
    Parses detailed listing info. Required by verify_app.py.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Description
    desc_tag = soup.find("div", {"data-cy": "ad_description"})
    if not desc_tag:
        desc_tag = soup.find("div", {"data-testid": "ad_description"})
    if not desc_tag:
        desc_tag = soup.find("div", {"data-testid": "description-section"})
    if not desc_tag:
        desc_tag = soup.find("div", class_=re.compile("description|content", re.I))
    description = desc_tag.get_text().strip() if desc_tag else ""
    
    # Image lists
    images_list = []
    images = soup.find_all("img")
    for img in images:
        src = img.get("src")
        if src and src.startswith("http") and ("olxcdn.com" in src or "olx.ua" in src):
            images_list.append(src)
            
    image_url = images_list[0] if images_list else None
    if not image_url:
        # Fallback to any absolute img src
        for img in images:
            src = img.get("src")
            if src and src.startswith("http"):
                image_url = src
                images_list.append(src)
                break
                
    # Parameters
    parameters = {}
    for tag in soup.find_all(["div", "span", "p", "li"]):
        if tag.find() is None:  # Leaf tag
            text = tag.get_text().strip()
            if ":" in text:
                parts = text.split(":", 1)
                k = parts[0].strip()
                v = parts[1].strip()
                if len(k) < 30 and len(v) < 100:
                    parameters[k] = v
                    
    return ListingDetails(
        description=description,
        image_url=image_url,
        images=images_list,
        parameters=parameters
    )

def parse_details_page(html_content: str, url: str, fallback_title: str = "") -> ScrapedAdDetails:
    """
    Detailed parser for monitor loop, returning rich metadata.
    Uses multiple selector strategies to reliably extract title from OLX Ukraine.
    Falls back to fallback_title (from search results) if parsing fails.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    olx_id = extract_olx_id(url)
    
    # Title — try multiple OLX-specific selectors in priority order
    title = ""
    title_selectors = [
        lambda s: s.find("h1", {"data-cy": "ad_title"}),
        lambda s: s.find("h1", {"data-testid": "ad_title"}),
        lambda s: s.find("h4", {"data-cy": "ad_title"}),
        lambda s: s.find(attrs={"data-cy": "ad_title"}),
        lambda s: s.find(attrs={"data-testid": "ad_title"}),
        lambda s: s.find("h1", itemprop="name"),
        lambda s: s.find("meta", {"property": "og:title"}),
        lambda s: s.find("h1"),
        lambda s: s.find("title"),
    ]
    for selector in title_selectors:
        tag = selector(soup)
        if tag:
            text = tag.get("content") or tag.get_text()
            text = text.strip()
            # Reject generic/empty values
            if text and text not in ("No Title", "", "OLX") and len(text) > 2:
                title = text
                break
                
    # Final fallback: use title from search listing
    if not title or title == "No Title":
        title = fallback_title
        if title:
            logger.debug("Used fallback title from search listing: '{}'", title)
        else:
            logger.warning("Could not extract title from detail page: {}", url)
            title = "Без назви"
    
    # Price
    price_tag = soup.find("h3", {"data-cy": "ad_price"})
    if not price_tag:
        price_tag = soup.find("h3", {"data-testid": "ad_price"})
    if not price_tag:
        price_tag = soup.find(attrs={"data-cy": "ad_price"})
    if not price_tag:
        price_tag = soup.find(attrs={"data-testid": "ad_price"})
    if not price_tag:
        # Try meta og:price
        meta_price = soup.find("meta", {"property": "product:price:amount"})
        if meta_price:
            price_str = meta_price.get("content", "0")
        else:
            price_str = "0"
    else:
        price_str = price_tag.get_text().strip()
    price = clean_price(price_str)
    
    # Description
    details_base = parse_details(html_content)
    
    # Location — try multiple selectors
    location = None
    for loc_sel in [
        {"data-cy": "ad-location"},
        {"data-testid": "ad-location"},
    ]:
        loc_tag = soup.find(attrs=loc_sel)
        if loc_tag:
            location = loc_tag.get_text().strip()
            break
    if not location:
        loc_tag = soup.find(class_=re.compile(r"location|address", re.I))
        if loc_tag:
            location = loc_tag.get_text().strip()
    
    # Date published — try multiple selectors
    date_str = None
    for date_sel in [
        {"data-cy": "ad-posted-at"},
        {"data-testid": "ad-posted-at"},
    ]:
        date_tag = soup.find(attrs=date_sel)
        if date_tag:
            date_str = date_tag.get_text().strip()
            break
    if not date_str:
        date_tag = soup.find(class_=re.compile(r"posted|created", re.I))
        if date_tag:
            date_str = date_tag.get_text().strip()
    published_at = parse_olx_datetime(date_str)
    
    return ScrapedAdDetails(
        olx_id=olx_id,
        title=title,
        price=price,
        url=url,
        location=location,
        description=details_base.description,
        image_url=details_base.image_url,
        published_at=published_at
    )
