# datapipe

A small data-analysis pipeline for small businesses. Point it at a few files (CSV, Excel, JSON, or a Google Sheets export link), describe the cleaning and the numbers you want in one JSON file, and get an HTML report plus JSON/CSV files for a dashboard.

- **Python standard library only.** No pip install, no API key, no cloud service. Your data stays on your computer.
- **One config file** describes sources, cleaning, joins and metrics. No code to write.
- **Honest about your data.** Every run reports duplicates removed, rows dropped, unreadable values, missing values and outliers.
- Français : voir [README.fr.md](README.fr.md).

## What it does

1. **Loads** several sources: `.csv` (delimiter detected), `.xlsx` (built-in reader), `.json`, or a URL.
2. **Cleans** each one: renames columns, converts types (`number`, `money`, `int`, `date`, `bool`), removes duplicates, drops rows missing required fields, fills blanks, filters rows, and adds computed columns (`revenue - cost`).
3. **Joins** sources on a key (`left` or `inner`).
4. **Computes metrics**: `sum`, `mean`, `median`, `min`, `max`, `count`, `distinct`, `ratio` (sum of one column over sum of another, for example revenue per hour), `rate` (share of true values, in percent), grouped by a column or by `day`, `week`, `month`, `quarter`, `year`.
5. **Writes** `report.html` (key figures, plain-language findings, charts, tables, data quality), `export/<metric>.json` for dashboards, `export/summary.json`, and optionally the cleaned tables as CSV.

The findings are written by rules, not by an AI: top group and its share, latest period against the previous one, best and weakest period, overall direction. The last period is left out of comparisons when the data stops before its end, and the table marks it as incomplete.

## Quick start

```bash
python datapipe.py profile data/sales.csv          # what is in this file? types, missing values, ranges
cp config.example.json config.json                 # describe your sources and metrics
python datapipe.py run --config config.json
```

Try the fictional example (a small moving company):

```bash
python examples/moving-company/make_sample_data.py
python datapipe.py run --config examples/moving-company/config.json
```

Open `examples/moving-company/out/rapport.html`. All data in the example is made up.

## Config reference

| Key | Meaning |
|---|---|
| `sources.<name>.path` or `.url` | A file next to the config, or a link. `type` is `csv`, `xlsx` or `json` (guessed from the name). `sheet` picks an Excel sheet. |
| `columns` | Rename columns: `{"Order Date": "date"}`. Other column names are lower-cased with underscores. |
| `types` | `{"date": "date", "amount": "money"}`. `money` understands `1 234,56 $`, `1,234.56`, `(12.50)`. |
| `date_order` | `dmy` (default) or `mdy`, for dates such as `05/03/2026`. Excel serial numbers are read too. |
| `dedupe` | Columns that identify a row (`["order_id"]`), or `"all"`. First row wins. |
| `drop_missing`, `fill`, `filters` | Required columns, default values, and row filters (`eq ne gt gte lt lte in not_in contains`). |
| `derived` | `[{"name": "margin", "expr": "revenue - cost"}]`. Arithmetic on columns only. |
| `joins` | `[{"name": "orders_customers", "left": "orders", "right": "customers", "on": ["customer_id"], "how": "left"}]`. |
| `metrics` | `{"id", "label", "source", "measure", "field", "by", "where", "top", "unit"}`. For `ratio` use `num` and `den`. |
| `kpis` | Metric ids with no `by`, shown as big numbers at the top of the report. |
| `outputs` | `dir`, `html`, `clean_csv`. |

Full examples: [config.example.json](config.example.json) and [examples/moving-company/config.json](examples/moving-company/config.json).

## Good to know

- Read the data-quality section of the report before trusting a number. A metric is only as good as the file it comes from.
- Ambiguous dates (`05/03/2026`) follow `date_order`. Check it on a sample.
- It does not forecast and it does not explain causes. It reports what is in the data.
- Your files may hold personal data. Keep them on a machine you control and follow your local privacy law.

## Tests

```bash
python -m unittest discover -s tests
```

## Use with Claude (optional)

See [docs/claude.md](docs/claude.md): a scheduled weekly or monthly run, and a dashboard artifact.

## License

MIT, see [LICENSE](LICENSE).
