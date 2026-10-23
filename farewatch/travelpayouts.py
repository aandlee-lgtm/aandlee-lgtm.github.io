"""Travelpayouts / Aviasales Data API client: rate-limited, retries only transient errors."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.travelpayouts.com"


class ApiError(Exception):
    def __init__(self, message, permanent):
        super().__init__(message)
        self.permanent = permanent


class Client:
    def __init__(self, token, pause=0.4, attempts=4):
        if not token:
            raise ApiError("TRAVELPAYOUTS_TOKEN is not set", permanent=True)
        self.token, self.pause, self.attempts = token, pause, attempts
        self.calls = 0

    def get(self, path, params=None):
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        request = urllib.request.Request(url, headers={"X-Access-Token": self.token,
                                                       "Accept-Encoding": "identity"})
        delay = 2
        for attempt in range(1, self.attempts + 1):
            time.sleep(self.pause)
            self.calls += 1
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code in (401, 403):
                    raise ApiError(f"{path}: HTTP {error.code} (token refused)", permanent=True)
                if error.code not in (429, 500, 502, 503, 504) or attempt == self.attempts:
                    raise ApiError(f"{path}: HTTP {error.code}", permanent=error.code < 500 and error.code != 429)
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt == self.attempts:
                    raise ApiError(f"{path}: {error}", permanent=False)
            time.sleep(delay)
            delay *= 2

    def prices_for_month(self, origin, destination, month):
        """Cached return fares departing in `month` (YYYY-MM), cheapest first, in AUD."""
        return self.get("/aviasales/v3/prices_for_dates", {
            "origin": origin, "destination": destination, "departure_at": month,
            "one_way": "false", "direct": "false", "currency": "aud", "market": "au",
            "sorting": "price", "limit": 1000,
        })

    def one_way_for_date(self, origin, destination, date):
        """Cached one-way fares departing on `date` (YYYY-MM-DD), cheapest first, in AUD."""
        return self.get("/aviasales/v3/prices_for_dates", {
            "origin": origin, "destination": destination, "departure_at": date,
            "one_way": "true", "currency": "aud", "market": "au",
            "sorting": "price", "unique": "false", "limit": 1000,
        })

    def airports(self):
        rows = self.get("/data/en/airports.json")
        return {row["code"]: {"country": row.get("country_code"), "name": row.get("name") or row["code"]}
                for row in rows if row.get("code")}

    def airlines(self):
        rows = self.get("/data/en/airlines.json")
        return {row["code"]: row.get("name") or row["code"] for row in rows if row.get("code")}
