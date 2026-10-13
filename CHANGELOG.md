# Changelog

All notable changes to Betteroff. Versions follow [semantic versioning](https://semver.org/). Add entries under Unreleased; `scripts/publish.sh` moves them under a dated version heading when you release.

## [Unreleased]

## [0.3.0] - 2026-10-12

- `betteroff cache prune` deletes older snapshots, keeping the newest per question (`--keep`, default 1) and always the latest; `--dry-run` lists what it would delete.
- Charts use Inter instead of Roboto, still falling back to Helvetica, Arial and sans-serif. Choose another family with `chart --font`, `font =` in recipes, `ds.chart(font=...)` or the `BETTEROFF_FONT` environment variable. Chart sidecars record the font, and the static-export check now looks for whichever font you chose.
- `chart --responses` draws only the responses you name, by id or by polarity (`positive,negative`), in charts, recipes (`responses =`) and `ds.chart(responses=...)`. The subtitle lists what's left out, and colors don't change.
- `--monthly/--no-monthly` replaces `--no-raw` for hiding the thin monthly lines behind a rolling average; the recipe key and Python argument are now `monthly`. The old names still work. Chart sidecars record `monthly` and `responses` instead of `raw`.
- Direct labels reserve a little more room at the right edge so wider fonts don't crowd it.
- Processes sharing a cache no longer overwrite each other's manifest updates; writes now take turns through a lock file.

## [0.2.0] - 2026-10-12

- Color themes for charts: `okabe-ito` (new default), `puor`, `brbg`, `rdbu` and `tol`, or your own TOML file. Choose one with `chart --theme`, `theme =` in recipes or `ds.chart(theme=...)`; `betteroff themes` lists them with swatches.
- Neutral responses are now a mid gray instead of purple, and nonresponse lines are thinner and dashed, so the favorable and unfavorable lines stand out.
- Chart sidecars record the theme name and colors.

## [0.1.0] - 2026-10-12

First release.

- Catalog of 18 Surveys of Consumers tables in the historical three-category layout, searchable offline by id, table number, title, keywords and wording.
- `get` fetches, validates and caches Michigan's historical Excel files and exports tidy or wide CSV and JSON with a metadata sidecar. `--measure index` returns Michigan's index score.
- `chart` makes HTML, SVG, PNG, PDF and Vega-Lite charts with polarity colors, direct labels, monthly tooltips, trailing averages, NBER recession shading and explicit gaps for missing months.
- `run` rebuilds declared outputs from a TOML recipe and records the snapshot behind each one.
- Content-addressed snapshots with revision reports; failed or invalid refreshes never replace the last good snapshot.
- Exit codes 2, 3 and 4 for input, fetch and validation failures.
