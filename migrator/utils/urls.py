def _redact_url(url: str) -> str:
    """Replace the password/token in an HTTPS URL with *** for safe logging."""
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    if parsed.password:
        netloc = f"{parsed.username}:***@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        safe = parsed._replace(netloc=netloc)
        return str(urlunparse(safe))
    return url
