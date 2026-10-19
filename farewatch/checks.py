"""Checks every fare must pass before it is shown: A$, freshness, trip length, routing.

Nothing here invents or adjusts a price. A fare that fails a check is dropped, and the reason
is counted so the page can report it.
"""

import datetime as dt
import re
import urllib.parse

# Airports in these countries may not be used for a connection or technical stop.
EXCLUDED_COUNTRIES = {
    "AE": "United Arab Emirates", "QA": "Qatar", "BH": "Bahrain", "SA": "Saudi Arabia",
    "OM": "Oman", "KW": "Kuwait", "JO": "Jordan", "LB": "Lebanon", "IL": "Israel", "IR": "Iran",
    "IQ": "Iraq", "SY": "Syria", "YE": "Yemen", "TR": "Türkiye", "EG": "Egypt",
}

# Airlines based there connect through their home hub, so their fares are rejected outright.
EXCLUDED_CARRIERS = {
    "EK", "FZ", "QR", "EY", "G9", "GF", "WY", "SV", "XY", "KU", "J9", "RJ", "ME", "LY", "IR",
    "W5", "IA", "TK", "PC", "XQ", "MS",
}

MIN_PLAUSIBLE_AUD = 150
MAX_PLAUSIBLE_AUD = 20000


class Rejected(Exception):
    """A fare failed a check; the message is the reason shown in diagnostics."""


def parse_link(link):
    """Read what the Aviasales link itself says about the fare.

    Returns found date, the currency and amount the link was created for, and the airports
    flown on each leg (from the `t` parameter, e.g. SYDPVGNRT). Missing parts are None.
    """
    parsed = urllib.parse.urlparse(link or "")
    query = urllib.parse.parse_qs(parsed.query)

    def one(name):
        values = query.get(name)
        return values[0] if values else None

    found = None
    raw_date = one("search_date")
    if raw_date and re.fullmatch(r"\d{8}", raw_date):
        try:
            found = dt.datetime.strptime(raw_date, "%d%m%Y").date()
        except ValueError:
            found = None

    price = one("expected_price")
    legs = []
    token = (one("t") or "").split("_")[0]
    for chain in re.findall(r"(?<=\d)([A-Z]{6,})(?=\d|$)", token):
        if len(chain) % 3 == 0:
            legs.append([chain[i:i + 3] for i in range(0, len(chain), 3)])
    return {
        "found": found,
        "currency": (one("expected_price_currency") or "").lower() or None,
        "price": int(price) if price and price.isdigit() else None,
        "legs": legs,
    }


def check_aud(response_currency, price, link_info):
    """Three independent A$ checks; raises Rejected on any failure."""
    if (response_currency or "").lower() != "aud":
        raise Rejected("not AUD (response)")
    if link_info["currency"] != "aud":
        raise Rejected("not AUD (link)")
    if link_info["price"] != price:
        raise Rejected("link price differs")
    if not MIN_PLAUSIBLE_AUD <= price <= MAX_PLAUSIBLE_AUD:
        raise Rejected("implausible amount")


def check_fresh(found, today, max_age_days):
    if found is None:
        raise Rejected("date found unknown")
    age = (today - found).days
    if age < 0 or age > max_age_days:
        raise Rejected("older than limit")
    return age


def nights(departure_at, return_at):
    out = dt.date.fromisoformat(departure_at[:10])
    back = dt.date.fromisoformat(return_at[:10])
    return (back - out).days


def check_routing(airline, legs, airports):
    """Return (status, via) where status is "verified" or "unverified"; raise Rejected if banned.

    `airports` maps IATA airport code -> {"country": ISO code, "name": str}.
    """
    if airline in EXCLUDED_CARRIERS:
        raise Rejected("Middle East / Türkiye airline")
    via, known = [], bool(legs)
    for leg in legs:
        for code in leg[1:-1]:
            info = airports.get(code)
            if info is None:
                known = False
                via.append(code)
                continue
            if info["country"] in EXCLUDED_COUNTRIES:
                raise Rejected("connects in Middle East / Türkiye")
            via.append(code)
    unique = list(dict.fromkeys(via))
    return ("verified" if known else "unverified"), unique
