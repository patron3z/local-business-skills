# local-business-skills

Two Claude skills for small local businesses. Both are plain Python (standard library only, no API key) and run on your own computer.

| Skill | What it does |
|---|---|
| [`competitor-watch`](plugins/local-business-tools/skills/competitor-watch) | Maps the local competition by area (Google Maps listings, ratings, reviews) and tracks the prices competitors publish on their own websites, with a change report on each run. |
| [`datapipe`](plugins/local-business-tools/skills/datapipe) | Loads exports (CSV, Excel, JSON), cleans and joins them, computes metrics (revenue by month, revenue per hour, conversion by source) and writes an HTML report with findings, charts and a data-quality check. |

Ask Claude things like "who are my competitors in Laval and what do they charge?" or "here are my QuickBooks exports, give me a report by month", and the matching skill takes over. Français : voir plus bas.

## Install

**Claude Code (plugin):**

```
/plugin marketplace add patron3z/local-business-skills
/plugin install local-business-tools@local-business-skills
```

The repository is private by default; the command works for the account that owns it. Make it public if you want others to install it.

**Claude Code (manual):** copy `plugins/local-business-tools/skills/competitor-watch` and `.../datapipe` into `~/.claude/skills/`.

**Claude.ai and Claude desktop:** run `python tools/build_zips.py`, then in Claude open Customize, Skills, add a skill, and upload each zip from `dist/`. Code execution must be enabled.

## Requirements

- Python 3.9 or newer. Nothing to `pip install`.
- For `competitor-watch` Google Maps collection only: the [Google Maps scraper kit](https://github.com/Mahanaicoach/google-maps-scraper-kit) and Google Chrome. You can skip it and bring a CSV instead. Check the kit's own licence (AGPL-3.0 with a commercial option) if you build a paid service on it.

## Good to know

- Scraping Google Maps is against Google's terms of service. Keep volumes small and treat results as leads to verify.
- Prices are read from websites by simple rules: verify them before deciding anything.
- The tools never send messages and never contact businesses.
- Your data files may hold personal data: keep them on a machine you control.

## Tests

```bash
cd plugins/local-business-tools/skills/competitor-watch && python -m unittest discover -s tests
cd ../datapipe && python -m unittest discover -s tests
```

## Standalone versions

The same tools exist as ordinary command-line projects: `competitor-watch` and `datapipe` (see their own READMEs for the full configuration reference, which is also in each skill's `references/` folder).

## Français

Deux skills Claude pour petites entreprises locales, en Python pur (bibliothèque standard, aucune clé). `competitor-watch` cartographie la concurrence par secteur et suit les prix publiés sur les sites des concurrents. `datapipe` nettoie des exports (CSV, Excel, JSON), calcule des indicateurs et écrit un rapport HTML avec constats, graphiques et bilan de qualité des données.

Installation dans Claude Code : `/plugin marketplace add patron3z/local-business-skills` puis `/plugin install local-business-tools@local-business-skills`. Pour claude.ai : `python tools/build_zips.py` et téléverser chaque zip du dossier `dist/`.

## License

MIT, see [LICENSE](LICENSE).
