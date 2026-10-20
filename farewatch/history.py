"""Daily observations, kept in data/history.jsonl so trends come only from real recorded fares."""

import datetime as dt
import json
import os

MIN_DAYS_FOR_TREND = 14


def append(path, result):
    """Record today's fares; a second scan on the same day replaces that day's rows."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            kept = [line for line in handle if json.loads(line)["date"] != result["today"]]
        with open(path, "w", encoding="utf-8") as handle:
            handle.writelines(kept)
    with open(path, "a", encoding="utf-8") as handle:
        for city in result["cities"]:
            for month, fare in city["months"].items():
                if fare:
                    handle.write(json.dumps({
                        "date": result["today"], "city": city["name"], "month": month,
                        "price": fare["price"], "depart": fare["depart"], "return": fare["return"],
                        "airline": fare["airline"], "found": fare["found"],
                    }) + "\n")


def lowest_recent(path, today, days=30):
    """{city: lowest price} over the previous `days`, only once enough days are recorded."""
    if not os.path.exists(path):
        return {}, 0
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=days)).isoformat()
    lows, dates = {}, set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if since <= row["date"] < today:
                dates.add(row["date"])
                lows[row["city"]] = min(row["price"], lows.get(row["city"], row["price"]))
    return (lows if len(dates) >= MIN_DAYS_FOR_TREND else {}), len(dates)
