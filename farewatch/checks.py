"""Checks every fare must pass before it is shown: A$, freshness, trip length, routing.

Nothing here invents or adjusts a price. A fare that fails a check is dropped, and the reason
is counted so the page can report it.
"""

import datetime as dt
import re
import urllib.parse

# Countries whose airports may be excluded as connections (owner's setting
# `excluded_transit_countries` in watchlist.toml). Names are used in the page and diagnostics.
COUNTRY_NAMES = {
    "AE": "United Arab Emirates", "QA": "Qatar", "BH": "Bahrain", "SA": "Saudi Arabia",
    "OM": "Oman", "KW": "Kuwait", "JO": "Jordan", "LB": "Lebanon", "IL": "Israel", "IR": "Iran",
    "IQ": "Iraq", "SY": "Syria", "YE": "Yemen", "TR": "Türkiye", "EG": "Egypt",
}

# Airlines whose fares always connect through a hub in their home country.
HUB_CARRIER_COUNTRY = {
    "EK": "AE", "FZ": "AE", "EY": "AE", "G9": "AE", "QR": "QA", "GF": "BH", "WY": "OM",
    "SV": "SA", "XY": "SA", "KU": "KW", "J9": "KW", "RJ": "JO", "ME": "LB", "LY": "IL",
    "IR": "IR", "W5": "IR", "IA": "IQ", "TK": "TR", "PC": "TR", "XQ": "TR", "MS": "EG",
}

# Since 13 Nov 2026 only Türkiye is excluded by default; the Middle East is allowed.
DEFAULT_EXCLUDED_COUNTRIES = ("TR",)

MIN_PLAUSIBLE_AUD = 150          # international return
MIN_PLAUSIBLE_ONE_WAY_AUD = 30   # domestic one way (real Sydney–Adelaide fares go below A$150)
MAX_PLAUSIBLE_AUD = 20000


class Rejected(Exception):
    """A fare failed a check; the message is the reason shown in diagnostics."""


def parse_link(link):
    """Read what the Aviasales link itself says about the fare.

    Returns found date, the currency and amount the link was created for, the airports flown on
    each leg and the airlines selling the trip (both from the `t` parameter, e.g. MU…SYDPVGNRT).
    Missing parts are None or empty.
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
    head = re.match(r"([A-Z0-9]*?)\d{8}", token)
    prefix = head.group(1) if head else ""
    carriers = [prefix[i:i + 2] for i in range(0, len(prefix), 2)] if len(prefix) % 2 == 0 else []
    return {
        "found": found,
        "currency": (one("expected_price_currency") or "").lower() or None,
        "price": int(price) if price and price.isdigit() else None,
        "legs": legs,
        "carriers": carriers,
    }


def check_aud(response_currency, price, link_info, minimum=MIN_PLAUSIBLE_AUD):
    """Three independent A$ checks; raises Rejected on any failure."""
    if (response_currency or "").lower() != "aud":
        raise Rejected("not AUD (response)")
    if link_info["currency"] != "aud":
        raise Rejected("not AUD (link)")
    if link_info["price"] != price:
        raise Rejected("link price differs")
    if not minimum <= price <= MAX_PLAUSIBLE_AUD:
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


def check_routing(airline, legs, airports, excluded=DEFAULT_EXCLUDED_COUNTRIES):
    """Return (status, via_per_leg); raise Rejected if the trip connects in an excluded country.

    status is "verified" when every connection airport is known, else "unverified".
    `airports` maps IATA airport code -> {"country": ISO code, "name": str}.
    """
    home = HUB_CARRIER_COUNTRY.get(airline)
    if home in excluded:
        raise Rejected(f"{COUNTRY_NAMES.get(home, home)} airline")
    known = bool(legs)
    via_per_leg = []
    for leg in legs:
        stops = []
        for code in leg[1:-1]:
            info = airports.get(code)
            if info is None:
                known = False
            elif info["country"] in excluded:
                raise Rejected(f"connects in {COUNTRY_NAMES.get(info['country'], info['country'])}")
            stops.append(code)
        via_per_leg.append(stops)
    return ("verified" if known else "unverified"), via_per_leg


def loyalty_badges(carriers, programs):
    """[(programme name, "all" | "part")] for programmes that the selling airlines earn with."""
    badges = []
    for program in programs:
        earning = [code for code in carriers if code in program["airlines"]]
        if earning:
            badges.append((program["name"], "all" if len(earning) == len(carriers) else "part"))
    return badges
