"""The approximate browser and system of a session, from its `User-Agent` (nothing else kept).

Only a short name is stored ("Firefox", "Android"); the raw header is not. Unknown values are
stored as an empty string and the interface names them.
"""

from __future__ import annotations

# Order matters: Edge and Opera also say "Chrome"; Chrome also says "Safari".
_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("SamsungBrowser/", "Samsung Internet"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox"),
    ("CriOS/", "Chrome"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)
_SYSTEMS = (
    ("iPhone", "iOS"),
    ("iPad", "iPadOS"),
    ("Android", "Android"),
    ("CrOS", "ChromeOS"),
    ("Windows", "Windows"),
    ("Mac OS X", "macOS"),
    ("Macintosh", "macOS"),
    ("Linux", "Linux"),
)


def describe(user_agent: str | None) -> tuple[str, str]:
    """(browser, system) for that header; ("", "") when unknown."""
    text = (user_agent or "")[:512]
    browser = next((name for mark, name in _BROWSERS if mark in text), "")
    system = next((name for mark, name in _SYSTEMS if mark in text), "")
    return browser, system
