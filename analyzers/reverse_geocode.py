"""Offline reverse geocoding via local GeoNames dataset.

Uses the ``reverse_geocoder`` library which bundles a ~30 MB GeoNames
extract.  The dataset is loaded once on first call and kept in memory.
No network requests, no API keys, no rate limits.
"""

import logging

logger = logging.getLogger("facet.geocode")

# Lazy-loaded module reference
_rg = None


def _ensure_loaded():
    """Load reverse_geocoder on first use (takes ~1s for the GeoNames file)."""
    global _rg
    if _rg is None:
        try:
            import reverse_geocoder as rg
            # Pre-load the KD-tree (suppresses stdout progress bar)
            rg.search((0, 0))
            _rg = rg
        except ImportError:
            logger.warning("reverse_geocoder not installed — geocoding disabled")
            raise
    return _rg


# Country codes where admin1 region is useful for disambiguation
_SHOW_REGION_COUNTRIES = {"US", "CA", "AU", "BR", "CN", "IN", "RU", "MX", "DE", "IT", "ES", "FR"}

# ISO country code → English display name (common ones)
_COUNTRY_NAMES = {
    "AD": "Andorra", "AE": "UAE", "AF": "Afghanistan", "AL": "Albania",
    "AM": "Armenia", "AO": "Angola", "AR": "Argentina", "AT": "Austria",
    "AU": "Australia", "AZ": "Azerbaijan", "BA": "Bosnia", "BB": "Barbados",
    "BD": "Bangladesh", "BE": "Belgium", "BG": "Bulgaria", "BH": "Bahrain",
    "BO": "Bolivia", "BR": "Brazil", "BS": "Bahamas", "BT": "Bhutan",
    "BW": "Botswana", "BY": "Belarus", "BZ": "Belize", "CA": "Canada",
    "CD": "DR Congo", "CH": "Switzerland", "CI": "Ivory Coast", "CL": "Chile",
    "CM": "Cameroon", "CN": "China", "CO": "Colombia", "CR": "Costa Rica",
    "CU": "Cuba", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany",
    "DK": "Denmark", "DO": "Dominican Republic", "DZ": "Algeria",
    "EC": "Ecuador", "EE": "Estonia", "EG": "Egypt", "ES": "Spain",
    "ET": "Ethiopia", "FI": "Finland", "FJ": "Fiji", "FR": "France",
    "GB": "United Kingdom", "GE": "Georgia", "GH": "Ghana", "GR": "Greece",
    "GT": "Guatemala", "HK": "Hong Kong", "HN": "Honduras", "HR": "Croatia",
    "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel",
    "IN": "India", "IQ": "Iraq", "IR": "Iran", "IS": "Iceland",
    "IT": "Italy", "JM": "Jamaica", "JO": "Jordan", "JP": "Japan",
    "KE": "Kenya", "KG": "Kyrgyzstan", "KH": "Cambodia", "KR": "South Korea",
    "KW": "Kuwait", "KZ": "Kazakhstan", "LA": "Laos", "LB": "Lebanon",
    "LK": "Sri Lanka", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia",
    "LY": "Libya", "MA": "Morocco", "MC": "Monaco", "MD": "Moldova",
    "ME": "Montenegro", "MG": "Madagascar", "MK": "North Macedonia",
    "ML": "Mali", "MM": "Myanmar", "MN": "Mongolia", "MO": "Macau",
    "MT": "Malta", "MU": "Mauritius", "MV": "Maldives", "MW": "Malawi",
    "MX": "Mexico", "MY": "Malaysia", "MZ": "Mozambique", "NA": "Namibia",
    "NG": "Nigeria", "NI": "Nicaragua", "NL": "Netherlands", "NO": "Norway",
    "NP": "Nepal", "NZ": "New Zealand", "OM": "Oman", "PA": "Panama",
    "PE": "Peru", "PH": "Philippines", "PK": "Pakistan", "PL": "Poland",
    "PR": "Puerto Rico", "PS": "Palestine", "PT": "Portugal", "PY": "Paraguay",
    "QA": "Qatar", "RO": "Romania", "RS": "Serbia", "RU": "Russia",
    "RW": "Rwanda", "SA": "Saudi Arabia", "SC": "Seychelles", "SD": "Sudan",
    "SE": "Sweden", "SG": "Singapore", "SI": "Slovenia", "SK": "Slovakia",
    "SN": "Senegal", "SO": "Somalia", "SV": "El Salvador", "SY": "Syria",
    "TH": "Thailand", "TN": "Tunisia", "TR": "Turkey", "TT": "Trinidad",
    "TW": "Taiwan", "TZ": "Tanzania", "UA": "Ukraine", "UG": "Uganda",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan",
    "VA": "Vatican", "VE": "Venezuela", "VN": "Vietnam", "ZA": "South Africa",
    "ZM": "Zambia", "ZW": "Zimbabwe",
}


def reverse_geocode(lat, lon):
    """Return a formatted place name for the given coordinates.

    Returns:
        str: e.g. "Paris, France" or "Portland, Oregon" or "" on failure
    """
    try:
        rg = _ensure_loaded()
    except (ImportError, Exception):
        return ""

    try:
        results = rg.search((lat, lon))
        if not results:
            return ""

        r = results[0]
        city = r.get("name", "")
        admin1 = r.get("admin1", "")
        cc = r.get("cc", "")

        country = _COUNTRY_NAMES.get(cc, cc)

        if cc in _SHOW_REGION_COUNTRIES and admin1 and admin1 != city:
            return f"{city}, {admin1}" if city else admin1
        elif city:
            return f"{city}, {country}" if country else city
        elif country:
            return country
        return ""
    except Exception:
        logger.debug("Reverse geocode failed for (%s, %s)", lat, lon, exc_info=True)
        return ""


def reverse_geocode_batch(coords):
    """Batch reverse geocode a list of (lat, lon) tuples.

    Returns:
        list[str]: formatted place names, same length as input
    """
    try:
        rg = _ensure_loaded()
    except (ImportError, Exception):
        return [""] * len(coords)

    try:
        results = rg.search(coords)
        names = []
        for r in results:
            city = r.get("name", "")
            admin1 = r.get("admin1", "")
            cc = r.get("cc", "")
            country = _COUNTRY_NAMES.get(cc, cc)
            if cc in _SHOW_REGION_COUNTRIES and admin1 and admin1 != city:
                names.append(f"{city}, {admin1}" if city else admin1)
            elif city:
                names.append(f"{city}, {country}" if country else city)
            elif country:
                names.append(country)
            else:
                names.append("")
        return names
    except Exception:
        logger.debug("Batch reverse geocode failed", exc_info=True)
        return [""] * len(coords)
