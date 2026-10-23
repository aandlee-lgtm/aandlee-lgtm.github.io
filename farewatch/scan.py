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


def load_loyalty(path):
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    return [{"name": p["name"], "airlines": set(p["airlines"])} for p in data.get("loyalty", {}).values()]


def load_lookouts(path):
    with open(path, "rb") as handle:
        return tomllib.load(handle).get("lookout", [])


def months_from(today, count):
    year, month = today.year, today.month
    for _ in range(count + 1):
        yield f"{year:04d}-{month:02d}"
        month += 1
        if month == 13:
            year, month = year + 1, 1


def evaluate(item, currency, today, settings, airports, programs=()):
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
    routing, via_legs = checks.check_routing(item.get("airline"), info["legs"], airports)
    # The listed airline and the airline(s) in the link can differ on multi-airline trips; use both.
    carriers = [c for c in dict.fromkeys([item.get("airline")] + info["carriers"]) if c]
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
        "via_out": via_legs[0] if via_legs else None,
        "via_back": via_legs[1] if len(via_legs) > 1 else None,
        "routing": routing,
        "found": info["found"].isoformat(),
        "age_days": age,
        "link": AVIASALES + link,
        "loyalty": checks.loyalty_badges(carriers, programs),
    }


def evaluate_lookout(item, currency, today, settings, airports, programs, lookout):
    """One-way fare for a lookout: same real-fare checks, plus date, morning and airline."""
    link = item.get("link")
    if not link:
        raise checks.Rejected("no link")
    price = item.get("price")
    if not isinstance(price, int):
        raise checks.Rejected("no price")
    info = checks.parse_link(link)
    checks.check_aud(currency, price, info, checks.MIN_PLAUSIBLE_ONE_WAY_AUD)
    age = checks.check_fresh(info["found"], today, settings["max_age_days"])
    departs = item.get("departure_at") or ""
    if departs[:10] != lookout["date"]:
        raise checks.Rejected("other date")
    if departs[11:16] >= lookout["depart_before"]:
        raise checks.Rejected("not in the morning")
    carriers = [c for c in dict.fromkeys([item.get("airline")] + info["carriers"]) if c]
    if lookout["airline"] not in carriers:
        raise checks.Rejected("other airline")
    routing, via_legs = checks.check_routing(item.get("airline"), info["legs"], airports)
    return {
        "price": price, "depart_time": departs[11:16], "airline": item.get("airline"),
        "flight_number": item.get("flight_number"), "stops": item.get("transfers"),
        "via": via_legs[0] if via_legs else None, "routing": routing,
        "found": info["found"].isoformat(), "age_days": age, "link": AVIASALES + link,
        "loyalty": checks.loyalty_badges(carriers, programs),
    }


def run_lookout(client, origin, lookout, today, settings, airports, programs, errors):
    entry = {**lookout, "fare": None, "returned": 0, "drops": {}, "passed": lookout["date"] < today.isoformat()}
    if entry["passed"]:
        return entry
    try:
        body = client.one_way_for_date(origin, lookout["destination"], lookout["date"])
    except ApiError as error:
        if error.permanent and "token" in str(error):
            raise
        errors.append(f"{lookout['name']}: {error}")
        return entry
    drops = collections.Counter()
    for item in body.get("data") or []:
        entry["returned"] += 1
        try:
            fare = evaluate_lookout(item, body.get("currency"), today, settings, airports, programs, lookout)
        except checks.Rejected as reason:
            drops[str(reason)] += 1
            continue
        if entry["fare"] is None or fare["price"] < entry["fare"]["price"]:
            entry["fare"] = fare
    entry["drops"] = dict(drops)
    return entry


def run(client, origin, settings, cities, today, programs=(), lookouts=()):
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
                        fare = evaluate(item, body.get("currency"), today, settings, airports, programs)
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
    result["lookouts"] = [run_lookout(client, origin, lookout, today, settings, airports, programs, result["errors"])
                          for lookout in lookouts]
    result["airline_names"] = {code: airlines.get(code, code) for code in {l["airline"] for l in lookouts}}
    result["calls"] = client.calls
    result["airport_names"] = {code: airports[code]["name"] for city in result["cities"]
                               for fare in city["months"].values() if fare
                               for code in (fare["via_out"] or []) + (fare["via_back"] or []) + [fare["to_airport"]]
                               if code in airports}
    return result
