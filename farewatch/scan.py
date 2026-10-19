"""One daily scan: every watched city, every month ahead, every fare through every check."""

import collections
import datetime as dt
import tomllib

from . import checks
from .travelpayouts import ApiError

AVIASALES = "https://www.aviasales.com"


def load_watchlist(path):
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    settings = {"min_nights": 7, "max_nights": 42, "months_ahead": 12, "max_age_days": 3}
    settings.update(data.get("settings", {}))
    return data.get("origin", "SYD"), settings, data["city"]


def months_from(today, count):
    year, month = today.year, today.month
    for _ in range(count + 1):
        yield f"{year:04d}-{month:02d}"
        month += 1
        if month == 13:
            year, month = year + 1, 1


def evaluate(item, currency, today, settings, airports):
    """Turn one API item into a shown fare, or raise checks.Rejected with the reason."""
    link = item.get("link")
    if not link:
        raise checks.Rejected("no link")
    price = item.get("price")
    if not isinstance(price, int):
        raise checks.Rejected("no price")
    info = checks.parse_link(link)
    checks.check_aud(currency, price, info)
    age = checks.check_fresh(info["found"], today, settings["max_age_days"])
    try:
        length = checks.nights(item["departure_at"], item["return_at"])
    except (KeyError, TypeError, ValueError):
        raise checks.Rejected("dates missing")
    if not settings["min_nights"] <= length <= settings["max_nights"]:
        raise checks.Rejected("trip length outside 1–6 weeks")
    routing, via = checks.check_routing(item.get("airline"), info["legs"], airports)
    return {
        "price": price,
        "depart": item["departure_at"][:10],
        "return": item["return_at"][:10],
        "nights": length,
        "airline": item.get("airline"),
        "flight_number": item.get("flight_number"),
        "stops_out": item.get("transfers"),
        "stops_back": item.get("return_transfers"),
        "to_airport": item.get("destination_airport"),
        "via": via,
        "routing": routing,
        "found": info["found"].isoformat(),
        "age_days": age,
        "link": AVIASALES + link,
    }


def run(client, origin, settings, cities, today):
    """Return the scan result: per city, the cheapest real fare for each month, plus diagnostics."""
    airports = client.airports()
    airlines = client.airlines()
    result = {"cities": [], "errors": [], "today": today.isoformat()}
    for city in cities:
        months = {}
        drops = collections.Counter()
        returned = 0
        for month in months_from(today, settings["months_ahead"]):
            best = None
            for code in city["airports"]:
                try:
                    body = client.prices_for_month(origin, code, month)
                except ApiError as error:
                    if error.permanent and "token" in str(error):
                        raise
                    result["errors"].append(f"{city['name']} {month}: {error}")
                    continue
                if not body.get("success", False):
                    result["errors"].append(f"{city['name']} {month}: provider reported failure")
                    continue
                for item in body.get("data") or []:
                    returned += 1
                    try:
                        fare = evaluate(item, body.get("currency"), today, settings, airports)
                    except checks.Rejected as reason:
                        drops[str(reason)] += 1
                        continue
                    if best is None or fare["price"] < best["price"]:
                        best = fare
            if best:
                best["airline_name"] = airlines.get(best["airline"], best["airline"])
                best["compelling"] = best["price"] <= city["under_aud"]
            months[month] = best
        result["cities"].append({
            "name": city["name"], "under_aud": city["under_aud"], "months": months,
            "returned": returned, "drops": dict(drops),
        })
    result["calls"] = client.calls
    result["airport_names"] = {code: airports[code]["name"] for city in result["cities"]
                               for fare in city["months"].values() if fare
                               for code in fare["via"] + [fare["to_airport"]] if code in airports}
    return result
