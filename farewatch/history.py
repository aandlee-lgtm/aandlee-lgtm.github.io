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
                        "airline": fare["airline"], "found": fare["found"], "link": fare["link"],
                    }) + "\n")
        _append_lookouts(handle, result)


def _append_lookouts(handle, result):
    for lookout in result.get("lookouts", []):
        fare = lookout["fare"]
        if fare:
            handle.write(json.dumps({
                "date": result["today"], "lookout": lookout["name"], "flight_date": lookout["date"],
                "price": fare["price"], "depart_time": fare["depart_time"],
                "airline": fare["airline"], "found": fare["found"],
            }, ensure_ascii=False) + "\n")


def lookout_lows(path, today):
    """{lookout name: {date: cheapest real fare that day}} for earlier scan days."""
    lows = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if "lookout" in row and row["date"] < today:
                    days = lows.setdefault(row["lookout"], {})
                    days[row["date"]] = min(row["price"], days.get(row["date"], row["price"]))
    return lows


def lowest_recent(path, today, days=30):
    """{city: lowest recorded fare whose trip is still ahead}, once enough days are recorded.

    Each value is the history row of that fare plus "last_seen" (the last scan day it appeared).
    Fares whose departure date has passed are ignored: they can no longer be booked.
    """
    if not os.path.exists(path):
        return {}, 0
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=days)).isoformat()
    lows, dates, seen = {}, set(), {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if "city" not in row or not since <= row["date"] < today:
                continue
            dates.add(row["date"])
            key = (row["city"], row["depart"], row["return"], row["price"], row["airline"])
            seen[key] = max(row["date"], seen.get(key, row["date"]))
            if row["depart"] <= today:
                continue
            best = lows.get(row["city"])
            if best is None or row["price"] < best["price"]:
                lows[row["city"]] = dict(row)
    for city, row in lows.items():
        row["last_seen"] = seen[(city, row["depart"], row["return"], row["price"], row["airline"])]
    return (lows if len(dates) >= MIN_DAYS_FOR_TREND else {}), len(dates)


def daily_lows(path, today, days=60):
    """{city: {date: cheapest real fare recorded that day}} for earlier scan days."""
    if not os.path.exists(path):
        return {}
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=days)).isoformat()
    lows = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if "city" in row and since <= row["date"] < today:
                city = lows.setdefault(row["city"], {})
                city[row["date"]] = min(row["price"], city.get(row["date"], row["price"]))
    return lows
