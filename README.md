# Sydney Fare Watch

The page at https://aandlee-lgtm.github.io is rebuilt every morning by `.github/workflows/daily.yml`:
it scans real, recently found return fares from Sydney to the cities in `watchlist.toml` and
highlights any under your target price. All prices are in Australian dollars.

- **Change cities or target prices:** edit `watchlist.toml` on GitHub (pencil icon → Commit).
- **Run a scan now:** Actions → Daily fare scan → Run workflow.
- **Needs:** repository secret `TRAVELPAYOUTS_TOKEN` (Settings → Secrets and variables → Actions).

Project notes, decisions and history are kept in the private `Flight` repository.
