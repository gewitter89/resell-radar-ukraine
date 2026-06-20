import os
from app.utils.logger import logger

PROXIES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "proxies.txt"
)

_proxies = []
_index = 0

def load_proxies():
    """
    Loads SOCKS5/HTTP proxies from proxies.txt and environment variables.
    """
    global _proxies, _index
    _proxies = []
    _index = 0
    
    if os.path.exists(PROXIES_FILE):
        try:
            with open(PROXIES_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        _proxies.append(line)
        except Exception as e:
            logger.error("Failed to read proxies.txt: {}", e)
            
    # Fallback to env var
    env_proxies = os.environ.get("PROXIES", "")
    if env_proxies:
        for p in env_proxies.split(","):
            p = p.strip()
            if p:
                _proxies.append(p)
                
    if _proxies:
        logger.info("Proxy list loaded: {} active proxy endpoints found.", len(_proxies))
    else:
        logger.debug("No proxies configured. Using local connection IP.")

def get_next_proxy() -> str | None:
    """
    Returns the next proxy in sequence. Returns None if empty list.
    """
    global _index, _proxies
    if not _proxies:
        return None
        
    proxy = _proxies[_index % len(_proxies)]
    _index += 1
    return proxy

# Load on startup
load_proxies()
