"""Unit tests. All fares here are SYNTHETIC fixtures shaped like the provider's responses, never real fares."""

import datetime as dt
import os
import tempfile
import unittest

from farewatch import checks, history, report, scan

TODAY = dt.date(2026, 10, 19)
SETTINGS = {"min_nights": 7, "max_nights": 42, "months_ahead": 3, "max_age_days": 3}
AIRPORTS = {
    "SYD": {"country": "AU", "name": "Sydney"}, "NRT": {"country": "JP", "name": "Narita"},
    "PVG": {"country": "CN", "name": "Shanghai Pudong"}, "CDG": {"country": "FR", "name": "Paris CDG"},
    "DOH": {"country": "QA", "name": "Doha"}, "CAN": {"country": "CN", "name": "Guangzhou"},
}


def link(price=900, currency="aud", found="18102026", out="SYDPVGNRT", back="NRTPVGSYD"):
    return (f"/search/SYD0301TYO20011?t=MU17989776001799096100002095{out}18004641001800538500001120{back}_abc_1"
            f"&search_date={found}&expected_price_currency={currency}&expected_price={price}")


def item(price=900, depart="2027-01-03T12:00:00+11:00", ret="2027-01-20T16:55:00+09:00", airline="MU", **kw):
    return {"price": price, "departure_at": depart, "return_at": ret, "airline": airline,
            "transfers": 1, "return_transfers": 1, "destination_airport": "NRT", "flight_number": "562",
            "link": link(price=price, **kw)}


class LinkTest(unittest.TestCase):
    def test_parse(self):
        info = checks.parse_link(link())
        self.assertEqual(info["found"], dt.date(2026, 10, 18))
        self.assertEqual((info["currency"], info["price"]), ("aud", 900))
        self.assertEqual(info["legs"], [["SYD", "PVG", "NRT"], ["NRT", "PVG", "SYD"]])

    def test_missing_parts(self):
        info = checks.parse_link("/search/x")
        self.assertEqual((info["found"], info["currency"], info["price"], info["legs"]), (None, None, None, []))


class LoyaltyTest(unittest.TestCase):
    PROGRAMS = [{"name": "Velocity", "airlines": {"VA", "SQ"}}, {"name": "Sky Pearl", "airlines": {"CZ", "MF", "3U"}}]

    def test_carriers_read_from_link(self):
        self.assertEqual(checks.parse_link(link())["carriers"], ["MU"])
        self.assertEqual(checks.parse_link("/s?t=3U17989776001799096100002095SYDCANNRT_x")["carriers"], ["3U"])
        self.assertEqual(checks.parse_link("/s?t=CZMU17989776001799096100002095SYDCANNRT_x")["carriers"], ["CZ", "MU"])

    def test_badges(self):
        self.assertEqual(checks.loyalty_badges(["CZ"], self.PROGRAMS), [("Sky Pearl", "all")])
        self.assertEqual(checks.loyalty_badges(["CZ", "MU"], self.PROGRAMS), [("Sky Pearl", "part")])
        self.assertEqual(checks.loyalty_badges(["SQ"], self.PROGRAMS), [("Velocity", "all")])
        self.assertEqual(checks.loyalty_badges(["TR"], self.PROGRAMS), [])

    def test_badge_on_page(self):
        cz = item(price=900, airline="CZ")
        cz["link"] = cz["link"].replace("t=MU", "t=CZ")
        result = scan.run(FakeClient([cz]), "SYD", SETTINGS, CITIES, TODAY, self.PROGRAMS)
        fare = result["cities"][0]["months"]["2027-01"]
        self.assertEqual(fare["loyalty"], [("Sky Pearl", "all")])
        page = report.render(result, "SYD", SETTINGS, {}, 0, "now")
        self.assertIn('class="badge" title="May earn Sky Pearl', page)

    def test_listed_airline_and_link_airline_both_count(self):
        mixed = item(price=1900, airline="VA")
        mixed["link"] = mixed["link"].replace("t=MU", "t=MF")
        fare = scan.evaluate(mixed, "aud", TODAY, SETTINGS, AIRPORTS, self.PROGRAMS)
        self.assertEqual(fare["loyalty"], [("Velocity", "part"), ("Sky Pearl", "part")])

    def test_owner_programmes_load(self):
        names = {p["name"]: p["airlines"] for p in scan.load_loyalty("watchlist.toml")}
        self.assertIn("CZ", names["Sky Pearl"])
        self.assertIn("VA", names["Velocity"])
        self.assertNotIn("QR", names["Velocity"])          # excluded by the transit rule anyway


class EvaluateTest(unittest.TestCase):
    def ev(self, it, currency="aud"):
        return scan.evaluate(it, currency, TODAY, SETTINGS, AIRPORTS)

    def test_good_fare_kept(self):
        fare = self.ev(item())
        self.assertEqual((fare["price"], fare["nights"], fare["age_days"]), (900, 17, 1))
        self.assertEqual((fare["routing"], fare["via_out"], fare["via_back"]), ("verified", ["PVG"], ["PVG"]))
        self.assertTrue(fare["link"].startswith("https://www.aviasales.com/search/"))

    def assertDropped(self, it, reason, currency="aud"):
        with self.assertRaises(checks.Rejected) as caught:
            self.ev(it, currency)
        self.assertEqual(str(caught.exception), reason)

    def test_aud_triple_check(self):
        self.assertDropped(item(), "not AUD (response)", currency="usd")
        self.assertDropped(item(currency="usd"), "not AUD (link)")
        bad = item(); bad["price"] = 899
        self.assertDropped(bad, "link price differs")
        self.assertDropped(item(price=50), "implausible amount")

    def test_stale_fare_dropped(self):
        self.assertDropped(item(found="10102026"), "older than limit")
        self.assertDropped(item(found=""), "date found unknown")

    def test_trip_length(self):
        self.assertDropped(item(ret="2027-01-06T10:00:00+09:00"), "trip length outside 1–6 weeks")
        self.assertDropped(item(ret="2027-03-01T10:00:00+09:00"), "trip length outside 1–6 weeks")

    def test_middle_east_rejected(self):
        self.assertDropped(item(out="SYDDOHCDG"), "connects in Middle East / Türkiye")
        self.assertDropped(item(airline="QR"), "Middle East / Türkiye airline")

    def test_unknown_airport_is_unverified_not_hidden(self):
        fare = self.ev(item(out="SYDXXXNRT"))
        self.assertEqual(fare["routing"], "unverified")


class FakeClient:
    calls = 0

    def __init__(self, items):
        self.items = items

    def airports(self):
        return AIRPORTS

    def airlines(self):
        return {"MU": "China Eastern"}

    def prices_for_month(self, origin, destination, month):
        self.calls += 1
        rows = [i for i in self.items if i["departure_at"].startswith(month)]
        return {"success": True, "currency": "aud", "data": rows}


CITIES = [{"name": "Tokyo", "airports": ["TYO"], "under_aud": 1000}]


class RunAndReportTest(unittest.TestCase):
    def test_cheapest_per_month_and_compelling(self):
        client = FakeClient([item(price=1200), item(price=950), item(price=700, found="01102026")])
        result = scan.run(client, "SYD", SETTINGS, CITIES, TODAY)
        months = result["cities"][0]["months"]
        self.assertEqual(months["2027-01"]["price"], 950)       # the A$700 one is stale
        self.assertTrue(months["2027-01"]["compelling"])
        self.assertIsNone(months["2026-10"])
        self.assertEqual(result["cities"][0]["drops"], {"older than limit": 1})
        page = report.render(result, "SYD", SETTINGS, {}, 0, "Mon 19 Oct 2026, 6:17 AM")
        self.assertIn("Tokyo A$950", page)
        self.assertIn("curr=AUD", page)
        self.assertIn("emrldco.com", page)                      # Travelpayouts verification kept
        self.assertNotIn("A$700", page)

    def test_page_useful_when_nothing_found(self):
        result = scan.run(FakeClient([]), "SYD", SETTINGS, CITIES, TODAY)
        page = report.render(result, "SYD", SETTINGS, {}, 0, "now")
        self.assertIn("Nothing under your target prices today.", page)
        self.assertIn("No real fare found recently", page)

    def test_one_highlight_per_city(self):
        cities = CITIES + [{"name": "Osaka", "airports": ["OSA"], "under_aud": 1000}]
        fares = [item(price=800), item(price=850, depart="2027-02-03T12:00:00+11:00", ret="2027-02-20T10:00:00+09:00")]
        result = scan.run(FakeClient(fares), "SYD", dict(SETTINGS, months_ahead=4), cities, TODAY)
        page = report.render(result, "SYD", SETTINGS, {}, 0, "now")
        self.assertEqual(page.count('class="deal"'), 2)          # one Tokyo, one Osaka, not two Tokyo
        self.assertIn("PVG both ways", page)
        self.assertIn("Oct 2026 – Dec 2026", page)             # empty months collapsed into one row

    def test_every_price_on_the_page_is_aud(self):
        result = scan.run(FakeClient([item(price=950)]), "SYD", SETTINGS, CITIES, TODAY)
        page = report.render(result, "SYD", SETTINGS, {}, 0, "now")
        import re
        for match in re.finditer(r"(\S{0,3})\$\d", page):
            self.assertEqual(match.group(1)[-1:], "A", match.group(0))


class HistoryTest(unittest.TestCase):
    def test_trend_only_after_enough_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "h.jsonl")
            result = scan.run(FakeClient([item(price=950)]), "SYD", SETTINGS, CITIES, TODAY)
            for day in range(1, 15):
                result["today"] = (TODAY - dt.timedelta(days=day)).isoformat()
                history.append(path, result)
                lows, days = history.lowest_recent(path, TODAY.isoformat())
                self.assertEqual(lows, {} if day < 14 else {"Tokyo": 950})


class HistorySameDayTest(unittest.TestCase):
    def test_second_scan_same_day_replaces_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "h.jsonl")
            result = scan.run(FakeClient([item(price=950)]), "SYD", SETTINGS, CITIES, TODAY)
            history.append(path, result)
            history.append(path, result)
            with open(path) as handle:
                self.assertEqual(len(handle.readlines()), 1)


class TrendTest(unittest.TestCase):
    def test_daily_lows_from_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "h.jsonl")
            for day, price in (("2026-10-17", 990), ("2026-10-18", 950)):
                result = scan.run(FakeClient([item(price=price)]), "SYD", SETTINGS, CITIES, TODAY)
                result["today"] = day
                history.append(path, result)
            self.assertEqual(history.daily_lows(path, TODAY.isoformat()),
                             {"Tokyo": {"2026-10-17": 990, "2026-10-18": 950}})

    def test_trend_line_on_highlight(self):
        result = scan.run(FakeClient([item(price=900)]), "SYD", SETTINGS, CITIES, TODAY)
        trends = {"Tokyo": {"2026-10-17": 990, "2026-10-18": 950}}
        page = report.render(result, "SYD", SETTINGS, {}, 0, "now", trends)
        self.assertIn('<svg width="200"', page)
        self.assertIn("A$990 on 17 Oct → A$900 today · lowest A$900", page)
        self.assertIn("<title>18 Oct: A$950</title>", page)
        self.assertEqual(page.count("<svg"), 1)           # only in the "Worth a holiday?" section

    def test_no_line_with_one_day(self):
        result = scan.run(FakeClient([item(price=900)]), "SYD", SETTINGS, CITIES, TODAY)
        page = report.render(result, "SYD", SETTINGS, {}, 0, "now", {})
        self.assertNotIn("<svg", page)
        self.assertIn("line appears once there are two days of scans", page)


LOOKOUT = {"name": "Sydney → Adelaide", "destination": "ADL", "date": "2026-11-24",
           "airline": "VA", "depart_before": "12:00"}


def one_way(price=189, departs="2026-11-24T07:10:00+11:00", airline="VA", found="18102026"):
    return {"price": price, "departure_at": departs, "airline": airline, "flight_number": "410",
            "transfers": 0, "destination_airport": "ADL",
            "link": (f"/search/SYD2411ADL1?t={airline}17949852001794990900000125SYDADL_abc_1&search_date={found}"
                     f"&expected_price_currency=aud&expected_price={price}")}


class LookoutClient(FakeClient):
    def __init__(self, fares):
        super().__init__([])
        self.fares = fares

    def one_way_for_date(self, origin, destination, date):
        return {"success": True, "currency": "aud", "data": self.fares}


class LookoutTest(unittest.TestCase):
    PROGRAMS = [{"name": "Velocity", "airlines": {"VA"}}]

    def ev(self, it):
        return scan.evaluate_lookout(it, "aud", TODAY, SETTINGS, AIRPORTS, self.PROGRAMS, LOOKOUT)

    def test_virgin_morning_fare_kept(self):
        fare = self.ev(one_way())
        self.assertEqual((fare["price"], fare["depart_time"], fare["loyalty"]), (189, "07:10", [("Velocity", "all")]))

    def test_filters(self):
        for it, reason in ((one_way(departs="2026-11-24T13:05:00+11:00"), "not in the morning"),
                           (one_way(airline="JQ"), "other airline"),
                           (one_way(departs="2026-11-25T07:10:00+11:00"), "other date"),
                           (one_way(found="01102026"), "older than limit")):
            with self.assertRaises(checks.Rejected) as caught:
                self.ev(it)
            self.assertEqual(str(caught.exception), reason)

    def test_cheapest_kept_and_recorded(self):
        client = LookoutClient([one_way(price=219), one_way(price=189), one_way(price=99, airline="JQ")])
        result = scan.run(client, "SYD", SETTINGS, CITIES, TODAY, self.PROGRAMS, [LOOKOUT])
        entry = result["lookouts"][0]
        self.assertEqual((entry["fare"]["price"], entry["drops"]), (189, {"other airline": 1}))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "h.jsonl")
            history.append(path, result)
            self.assertEqual(history.lookout_lows(path, "2026-10-20"), {"Sydney → Adelaide": {"2026-10-19": 189}})
            self.assertEqual(history.daily_lows(path, "2026-10-20"), {})     # lookouts kept apart from cities
        page = report.render(result, "SYD", SETTINGS, {}, 0, "now", {}, {"Sydney → Adelaide": {"2026-10-17": 240}})
        self.assertIn("<h2>Lookout</h2>", page)
        self.assertIn("A$189</strong> · VA410 departs 7:10 am · non-stop", page)
        self.assertIn("A$240 on 17 Oct → A$189 today", page)
        self.assertIn("Search this morning on Google Flights (A$)", page)

    def test_no_fare_still_useful(self):
        result = scan.run(LookoutClient([]), "SYD", SETTINGS, CITIES, TODAY, self.PROGRAMS, [LOOKOUT])
        page = report.render(result, "SYD", SETTINGS, {}, 0, "now")
        self.assertIn("No real fare for this flight in today's data", page)
        self.assertIn("curr=AUD", page)

    def test_passed_date(self):
        result = scan.run(LookoutClient([one_way()]), "SYD", SETTINGS, CITIES, dt.date(2026, 11, 25),
                          self.PROGRAMS, [LOOKOUT])
        self.assertTrue(result["lookouts"][0]["passed"])
        self.assertIn("This flight date has passed.", report.render(result, "SYD", SETTINGS, {}, 0, "now"))


class WatchlistTest(unittest.TestCase):
    def test_owner_watchlist_loads(self):
        origin, settings, cities = scan.load_watchlist("watchlist.toml")
        self.assertEqual(origin, "SYD")
        self.assertEqual((settings["min_nights"], settings["max_nights"]), (7, 42))
        self.assertEqual({c["name"]: c["under_aud"] for c in cities}["Paris"], 1300)
        lookout = scan.load_lookouts("watchlist.toml")[0]
        self.assertEqual((lookout["destination"], lookout["date"], lookout["airline"]), ("ADL", "2026-11-24", "VA"))


if __name__ == "__main__":
    unittest.main()
