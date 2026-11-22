# competitor-watch

Map the local competition around you and keep an eye on the prices they publish. Works for any local business: movers, dentists, plumbers, restaurants, gyms.

- **Python standard library only.** No API key, no paid service, nothing to install with pip.
- **Config-driven.** Your market, your cities, your categories and your price format live in one JSON file.
- **Polite.** One request per page, `robots.txt` respected, a pause between pages.
- Français : voir [README.fr.md](README.fr.md).

## What it does

| Step | Command | Result |
|---|---|---|
| 1. Find businesses | `scrape` (optional) | A CSV of Google Maps listings per city, made by a local scraper kit |
| 2. Map the competition | `map` | An HTML report per area (count, average rating, top businesses) and a list of websites to watch |
| 3. Read their prices | `watch` | An HTML report of prices and promises found on each site, with what changed since the last visit |
| 4. Reuse the data | `export` | JSON files (areas, businesses, prices) for a dashboard or a spreadsheet |

Google Maps does not show prices. Prices come from the competitors' own websites (step 3).

## Quick start

```bash
cp config.example.json config.json        # edit: project, cities, services, price format
python competitor_watch.py scrape --service dentist                 # optional, needs the scraper kit
python competitor_watch.py map    --service dentist --csv data/maps/results-dentist-YYYY-MM-DD.csv
python competitor_watch.py watch                                    # reads every site once
python competitor_watch.py export --service dentist
```

Run `watch` again later (weekly or monthly): each run compares with the previous one and lists price changes.

No scraper kit? Skip step 1. Export a CSV from any Google Maps tool (columns used: `title, phone, website, category, address, review_rating, review_count`) and start at `map`. You can also list competitors by hand in the config (`competitors`) and use only `watch`.

## Configuration

See [config.example.json](config.example.json) and a full French example in [examples/moving-montreal.config.json](examples/moving-montreal.config.json).

| Key | Meaning |
|---|---|
| `project`, `language` | Title of the reports. `language` is `fr` or `en`. |
| `address.region_pattern` | Regex for the region part of an address (`QC`, `TX`, `Ontario`...). The area is the part just before it. |
| `maps.kit_path` | Folder of the Google Maps scraper kit (only for `scrape`). |
| `maps.cities`, `maps.lang`, `maps.country`, `maps.depth` | Where and how to search. Keep `depth` low (2 is about 40 results per city and keyword). |
| `services.<id>.keywords` | Searches sent to Google Maps. |
| `services.<id>.category_regex` | Keeps only listings whose category or name matches. |
| `services.<id>.price.mode` | `rate`: a number followed by a unit, such as `120 $/h` (set `unit_regex`, `min`, `max`). `amounts`: any amount between `min` and `max`. |
| `competitors` | Sites to watch by hand: `{ "name", "service", "pages": [urls] }`. |
| `directories_to_skip` | Domains never added to the watch list (social networks, directories). |

Everything is written under `data_dir` (default `data/`): `maps/`, `snapshots/`, `reports/`, `export/`.

## Good to know

- **Prices are read automatically** with simple rules. Check them on the site before basing a decision on them. Pages built with JavaScript may show little text (the report warns you).
- **Not every business publishes a price.** In the example market, only about one in seven did.
- **Google Maps scraping is against Google's terms of service.** Keep volumes small, treat results as leads to verify, do not resell raw data. Heavy runs can get your IP temporarily rate-limited.
- **Phone numbers and names are business listings,** but you remain responsible for how you store and use them under your local privacy law.
- This tool never sends messages and never contacts the businesses it lists.

## Tests

```bash
python -m unittest discover -s tests
```

## Use with Claude (optional)

See [docs/claude.md](docs/claude.md): a scheduled monthly run and a dashboard.

## License

MIT, see [LICENSE](LICENSE).
