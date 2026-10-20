"""Run the daily scan and write the page:  python -m farewatch --out index.html"""

import argparse
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

from . import history, report, scan
from .travelpayouts import ApiError, Client

SYDNEY = ZoneInfo("Australia/Sydney")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watchlist", default="watchlist.toml")
    parser.add_argument("--out", default="index.html")
    parser.add_argument("--history", default="data/history.jsonl")
    parser.add_argument("--no-history", action="store_true", help="do not record this run (previews)")
    args = parser.parse_args()

    now = dt.datetime.now(SYDNEY)
    origin, settings, cities = scan.load_watchlist(args.watchlist)
    try:
        client = Client(os.environ.get("TRAVELPAYOUTS_TOKEN", ""))
        result = scan.run(client, origin, settings, cities, now.date(), scan.load_loyalty(args.watchlist))
    except ApiError as error:
        # Leave the existing page untouched: a failed scan must never publish an empty or invented report.
        sys.exit(f"Scan failed, page not updated: {error}")

    lows, days = history.lowest_recent(args.history, result["today"])
    page = report.render(result, origin, settings, lows, days, now.strftime("%a %-d %b %Y, %-I:%M %p"))
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(page)
    if not args.no_history:
        history.append(args.history, result)

    for city in result["cities"]:
        shown = {m: f["price"] for m, f in city["months"].items() if f}
        print(f"{city['name']}: {len(shown)} months with a real fare; returned {city['returned']}; "
              f"dropped {json.dumps(city['drops'], ensure_ascii=False)}")
        for month, price in shown.items():
            flag = "  <= target" if price <= city["under_aud"] else ""
            print(f"    {month}: A${price}{flag}")
    for error in result["errors"]:
        print("ERROR", error)
    print(f"{result['calls']} provider requests")


if __name__ == "__main__":
    main()
