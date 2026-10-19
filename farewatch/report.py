"""Render the scan result as the static page people open: index.html."""

import datetime as dt
import html

from . import VERSION

HEAD_SCRIPT = """<!-- Travelpayouts site verification (Drive script) -->
<script nowprocket data-noptimize="1" data-cfasync="false" data-wpfc-render="false" seraph-accel-crit="1" data-no-defer="1" data-cmp-ab="2">
  (function () {
      var script = document.createElement("script");
      script.async = 1;
      script.setAttribute("data-cmp-ab","2");
      script.src = 'https://emrldco.com/NTg3NTk4.js?t=587598';
      document.head.appendChild(script);
  })();
</script>"""

STYLE = """
  :root { --bg:#f7f8fa; --card:#fff; --text:#1d2430; --muted:#5b6573; --accent:#0b6e8a;
          --good:#1b7f3b; --goodbg:#e7f5ec; --line:#e2e6eb; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#11161d; --card:#19202a; --text:#e6eaf0; --muted:#9aa5b3; --accent:#5cc3df;
            --good:#6fd08f; --goodbg:#16301f; --line:#2a3340; } }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  main { max-width:980px; margin:0 auto; padding:28px 16px 56px; }
  h1 { font-size:1.7rem; margin:0 0 4px; } h2 { font-size:1.15rem; margin:0 0 10px; }
  .muted { color:var(--muted); } .small { font-size:.85rem; }
  section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:14px 0; }
  .deal { border-left:4px solid var(--good); background:var(--goodbg); padding:10px 12px; border-radius:6px; margin:8px 0; }
  .price { font-weight:700; font-size:1.15rem; }
  .table { overflow-x:auto; }
  table { border-collapse:collapse; width:100%; min-width:640px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { font-size:.8rem; color:var(--muted); font-weight:600; }
  tr.hit td { background:var(--goodbg); }
  a { color:var(--accent); }
  details summary { cursor:pointer; color:var(--muted); }
  @media (max-width:640px) {
    .fares table, .fares tr, .fares td { display:block; min-width:0; width:auto; }
    .fares tr.head { display:none; }
    .fares tr { border-bottom:1px solid var(--line); padding:8px 4px; }
    .fares td { border:0; padding:1px 0; }
    .fares td[data-label]::before { content:attr(data-label) ": "; color:var(--muted); font-size:.8rem; } }
"""

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def esc(value):
    return html.escape(str(value), quote=True)


def aud(amount):
    return f"A${amount:,}"


def nice_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def nice_month(month):
    year, m = month.split("-")
    return f"{MONTHS[int(m) - 1]} {year}"


def found_text(age):
    return "today" if age == 0 else "yesterday" if age == 1 else f"{age} days ago"


def google_link(fare, origin):
    from urllib.parse import quote
    q = f"Flights from {origin} to {fare['to_airport']} on {fare['depart']} through {fare['return']}"
    return f"https://www.google.com/travel/flights?q={quote(q)}&curr=AUD&hl=en-AU&gl=AU"


def via_text(fare, names):
    """E.g. "Non-stop", "PVG both ways", "Out PVG · back CAN, SZX"; "(check)" if not all confirmed."""
    out, back = fare["via_out"], fare["via_back"]
    if out is None or back is None:
        stops = [fare["stops_out"], fare["stops_back"]]
        text = "Non-stop" if stops == [0, 0] else f"{stops[0]} stop(s) out, {stops[1]} back"
    elif not out and not back:
        text = "Non-stop"
    elif out == list(reversed(back)):
        text = f"{', '.join(out)} both ways"
    else:
        text = f"Out {', '.join(out) or 'non-stop'} · back {', '.join(back) or 'non-stop'}"
    return text + (" (check)" if fare["routing"] == "unverified" else "")


def links(fare, origin):
    return (f'<a href="{esc(fare["link"])}" rel="nofollow noopener" target="_blank">View fare</a>'
            f' · <a href="{esc(google_link(fare, origin))}" rel="nofollow noopener" target="_blank">Google Flights</a>')


def render(result, origin, settings, lows, history_days, generated_at):
    names = result.get("airport_names", {})
    deals = []
    for city in result["cities"]:
        for month, fare in city["months"].items():
            if fare and fare["compelling"]:
                deals.append((fare["price"] / city["under_aud"], city, fare))
    deals.sort(key=lambda d: d[0])
    best_per_city = {}
    for deal in deals:
        best_per_city.setdefault(deal[1]["name"], deal)
    deals = sorted(best_per_city.values(), key=lambda d: d[0])

    out = ["<!doctype html>", '<html lang="en-AU">', "<head>", '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           "<title>Sydney Fare Watch</title>",
           '<meta name="description" content="Daily watch for real, recently found return fares from Sydney, in Australian dollars.">',
           HEAD_SCRIPT, f"<style>{STYLE}</style>", "</head>", "<body>", "<main>",
           "<h1>Sydney Fare Watch</h1>",
           f'<p class="muted">Updated {esc(generated_at)} (Sydney time). Return fares from Sydney, 1 adult, economy, '
           f'{settings["min_nights"] // 7}–{settings["max_nights"] // 7} week trips, up to {settings["months_ahead"]} months ahead. '
           f'All prices in <strong>Australian dollars (A$)</strong>.</p>',
           f'<p class="muted small">Only fares that real travellers\' searches found in the last {settings["max_age_days"]} days are shown. '
           "Prices change and seats sell out: always confirm on the link before booking.</p>"]

    out.append("<section><h2>Worth a holiday?</h2>")
    if deals:
        for _, city, fare in deals[:3]:
            out.append(
                f'<div class="deal"><span class="price">{esc(city["name"])} {aud(fare["price"])}</span> return '
                f'<span class="muted">(your target: under {aud(city["under_aud"])})</span><br>'
                f'{nice_date(fare["depart"])} → {nice_date(fare["return"])}, {fare["nights"]} nights · '
                f'{esc(fare["airline_name"])} · {esc(via_text(fare, names))} · found {found_text(fare["age_days"])}<br>'
                f'{links(fare, origin)}</div>')
    else:
        out.append('<p style="margin:0">Nothing under your target prices today.</p>')
    out.append("</section>")

    for city in result["cities"]:
        seen = sum(1 for fare in city["months"].values() if fare)
        out.append(f'<section><h2>{esc(city["name"])} <span class="muted small">· target under {aud(city["under_aud"])}</span></h2>')
        if city["name"] in lows:
            out.append(f'<p class="small muted">Lowest we have recorded in the last 30 days: {aud(lows[city["name"]])}</p>')
        if not seen:
            out.append('<p style="margin:0">No real fare found recently for any month.</p></section>')
            continue
        out.append('<div class="table fares"><table><tr class="head"><th>Departing</th><th>Best real fare</th><th>Dates</th>'
                   '<th>Airline</th><th>Connections</th><th>Found</th><th></th></tr>')
        empty = []

        def flush_empty():
            if empty:
                label = nice_month(empty[0]) + (f" – {nice_month(empty[-1])}" if len(empty) > 1 else "")
                out.append(f'<tr><td><strong>{label}</strong></td><td colspan="6" class="muted">No recent fare</td></tr>')
                empty.clear()

        for month, fare in city["months"].items():
            if not fare:
                empty.append(month)
                continue
            flush_empty()
            row_class = ' class="hit"' if fare["compelling"] else ""
            out.append(
                f'<tr{row_class}><td><strong>{nice_month(month)}</strong></td><td data-label="Fare"><strong>{aud(fare["price"])}</strong></td>'
                f'<td data-label="Dates">{nice_date(fare["depart"])} → {nice_date(fare["return"])} <span class="muted small">({fare["nights"]} nights)</span></td>'
                f'<td data-label="Airline">{esc(fare["airline_name"])}</td><td data-label="Connections">{esc(via_text(fare, names))}</td>'
                f'<td data-label="Found">{found_text(fare["age_days"])}</td><td>{links(fare, origin)}</td></tr>')
        flush_empty()
        out.append("</table></div></section>")

    out.append("<section><details><summary>How this was checked</summary><div class=\"small\">")
    out.append("<p>Each fare shown passed every check: priced in AUD by the source, the booking link carries the same "
               "AUD amount, found by a real search within the time limit, a 1–6 week trip, and no connection in the "
               "Middle East or Türkiye (\"(check)\" means the connection airports could not all be confirmed). "
               "Source: Travelpayouts / Aviasales data; \"View fare\" opens a live Aviasales search, "
               "\"Google Flights\" opens the same dates there.</p>")
    out.append('<table><tr><th>City</th><th>Fares returned</th><th>Not shown, and why</th></tr>')
    for city in result["cities"]:
        why = ", ".join(f"{reason}: {count}" for reason, count in sorted(city["drops"].items(), key=lambda kv: -kv[1])) or "—"
        out.append(f'<tr><td>{esc(city["name"])}</td><td>{city["returned"]}</td><td>{esc(why)}</td></tr>')
    out.append("</table>")
    if result["errors"]:
        out.append("<p>Problems during this scan:</p><ul>" + "".join(f"<li>{esc(e)}</li>" for e in result["errors"]) + "</ul>")
    trend = (f"Trend data: {history_days} day(s) recorded so far; the 30-day low appears after 14 days."
             if not lows else "")
    out.append(f"<p class=\"muted\">{result['calls']} provider requests. {esc(trend)}</p></div></details></section>")
    out.append(f'<p class="muted small">Sydney Fare Watch {VERSION}</p></main></body></html>')
    return "\n".join(out) + "\n"
