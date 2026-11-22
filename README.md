# local-business-skills

Two [Agent Skills](https://agentskills.io) for small local businesses, for **Claude Code, Claude.ai, Codex, OpenCode and Gemini CLI**. Both are plain Python (standard library only, no API key) and run on your own computer.

| Skill | What it does |
|---|---|
| [`competitor-watch`](plugins/local-business-tools/skills/competitor-watch) | Maps the local competition by area (Google Maps listings, ratings, reviews) and tracks the prices competitors publish on their own websites, with a change report on each run. |
| [`datapipe`](plugins/local-business-tools/skills/datapipe) | Loads exports (CSV, Excel, JSON), cleans and joins them, computes metrics (revenue by month, revenue per hour, conversion by source) and writes an HTML report with findings, charts and a data-quality check. |

Ask your agent things like "who are my competitors in Laval and what do they charge?" or "here are my QuickBooks exports, give me a report by month", and the matching skill takes over. Français : voir plus bas.

## Install

**Claude Code (plugin):**

```
/plugin marketplace add patron3z/local-business-skills
/plugin install local-business-tools@local-business-skills
```

**Claude Code (manual):** copy `plugins/local-business-tools/skills/competitor-watch` and `.../datapipe` into `~/.claude/skills/`.

**Claude.ai and Claude desktop:** run `python tools/build_zips.py`, then in Claude open Customize, Skills, add a skill, and upload each zip from `dist/`. Code execution must be enabled.

**Codex, OpenCode, Gemini CLI.** Each skill is a plain folder with a `SKILL.md` (frontmatter `name` and `description`), the standard Agent Skills layout. Copy `competitor-watch` and `datapipe` from `plugins/local-business-tools/skills/` to the folder your tool reads:

| Tool | User-level folder | Project-level folder |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Codex | `~/.agents/skills/` | `.agents/skills/` |
| OpenCode | `~/.config/opencode/skills/` | `.opencode/skills/` |
| Gemini CLI | `~/.gemini/skills/` | `.gemini/skills/` |

OpenCode also reads `~/.claude/skills/` and `~/.agents/skills/`, so one copy can serve several tools. Gemini CLI can also install from a Git URL or a local folder with `gemini skills install`. Folder names differ between tool versions, so check your tool's current documentation. Compatibility here means the skill format and the `python scripts/...` commands; the scripts are tested as plain Python (29 unit tests), but the skills have not yet been run inside any of these agents.

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

Compatibles Claude Code, claude.ai, Codex, OpenCode et Gemini CLI (format Agent Skills : voir le tableau des dossiers plus haut). Installation dans Claude Code : `/plugin marketplace add patron3z/local-business-skills` puis `/plugin install local-business-tools@local-business-skills`. Pour claude.ai : `python tools/build_zips.py` et téléverser chaque zip du dossier `dist/`.

## License

MIT, see [LICENSE](LICENSE).
