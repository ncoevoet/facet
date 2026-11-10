"""Read a latitude/longitude pair out of what a user copies from Google Maps.

Pure and stdlib-only; mirrored by ``client/src/app/shared/utils/google-maps-link.ts``
(same rules, same order) so the server can resolve a short link to exactly the
point the browser would have read from the long one.

Accepted, in this order of preference for a URL:

1. ``!3dLAT!4dLON`` in the ``data=`` blob: the dropped pin / place itself;
2. ``q=`` / ``query=`` / ``ll=`` / ``center=`` / ``destination=`` query values;
3. ``@LAT,LON[,ZOOMz]``: the viewport centre;
4. a ``/maps/search/...`` or ``/maps/place/...`` path segment that is itself a pair.

Free text (no URL) may be a decimal pair (``32.6064, -116.3239`` or
``32.6064 -116.3239``) or a degrees/minutes/seconds pair
(``32°36'23.0"N 116°19'26.0"W``, minutes and seconds optional, decimal degrees
with a hemisphere letter allowed). Every result is range-checked: latitude in
[-90, 90], longitude in [-180, 180].
"""
import math
import re
from urllib.parse import parse_qsl, unquote, urlsplit

MAX_INPUT = 2048

_NUM = r'[-+]?\d{1,3}(?:\.\d+)?'
_DECIMAL_PAIR = re.compile(rf'^\s*({_NUM})\s*(?:,|;|\s)\s*({_NUM})\s*$')
_DMS_PART = (
    r'(\d{1,3}(?:\.\d+)?)\s*°\s*'
    r'(?:(\d{1,2}(?:\.\d+)?)\s*[\'′’]\s*)?'
    r'(?:(\d{1,2}(?:\.\d+)?)\s*(?:"|″|”|\'\'|′′)\s*)?'
    r'([NSEWnsew])'
)
_DMS_PAIR = re.compile(rf'^\s*{_DMS_PART}\s*,?\s*{_DMS_PART}\s*$')
_PIN = re.compile(rf'!3d({_NUM})!4d({_NUM})')
_AT = re.compile(rf'@({_NUM}),({_NUM})')
_QUERY_KEYS = ('q', 'query', 'll', 'center', 'destination')
_PATH = re.compile(r'/maps/(?:search|place)/([^/@]+)')


def _valid(lat: float, lon: float) -> tuple[float, float] | None:
    if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def _dms_value(deg: str, minutes: str | None, seconds: str | None, hemi: str) -> float | None:
    d = float(deg)
    m = float(minutes) if minutes else 0.0
    s = float(seconds) if seconds else 0.0
    if m >= 60 or s >= 60 or ((minutes or seconds) and d != int(d)):
        return None
    value = d + m / 60 + s / 3600
    return -value if hemi.upper() in 'SW' else value


def parse_pair(text: str) -> tuple[float, float] | None:
    """A free-text coordinate pair: decimal or DMS. ``None`` if it is neither."""
    if not isinstance(text, str) or len(text) > MAX_INPUT:
        return None
    match = _DECIMAL_PAIR.match(text)
    if match:
        return _valid(float(match.group(1)), float(match.group(2)))
    match = _DMS_PAIR.match(text)
    if match:
        g = match.groups()
        first, second = g[3].upper(), g[7].upper()
        if first in 'NS' and second in 'EW':
            lat, lon = _dms_value(*g[0:4]), _dms_value(*g[4:8])
        elif first in 'EW' and second in 'NS':
            lon, lat = _dms_value(*g[0:4]), _dms_value(*g[4:8])
        else:
            return None
        if lat is None or lon is None:
            return None
        return _valid(lat, lon)
    return None


def _decoded(url: str) -> str:
    """Percent-decoded twice: a consent page wraps the maps URL in ``continue=``."""
    return unquote(unquote(url))


def parse_url(url: str) -> tuple[float, float] | None:
    """Coordinates a Google Maps URL carries, by the module's preference order."""
    if not isinstance(url, str) or len(url) > MAX_INPUT:
        return None
    decoded = _decoded(url)
    pins = _PIN.findall(decoded)
    if pins:
        # The last pair in the data blob is the place the URL opens on.
        return _valid(float(pins[-1][0]), float(pins[-1][1]))
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    queries = [parts.query]
    # A wrapped URL (consent.google.com?continue=...) carries the real query inside.
    for _, wrapped in parse_qsl(parts.query, keep_blank_values=True):
        if wrapped.startswith(('http://', 'https://')):
            try:
                queries.append(urlsplit(wrapped).query)
            except ValueError:
                # A malformed wrapped URL (an unclosed IPv6 bracket) carries no point.
                continue
    for query in queries:
        params = dict(parse_qsl(query, keep_blank_values=True))
        for key in _QUERY_KEYS:
            value = params.get(key)
            if value:
                pair = parse_pair(value.removeprefix('loc:').strip())
                if pair:
                    return pair
    match = _AT.search(decoded)
    if match:
        return _valid(float(match.group(1)), float(match.group(2)))
    match = _PATH.search(decoded)
    if match:
        return parse_pair(match.group(1).replace('+', ' '))
    return None

