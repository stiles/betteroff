# Changelog

All notable changes to Betteroff. Versions follow [semantic versioning](https://semver.org/). Add entries under Unreleased; `scripts/publish.sh` moves them under a dated version heading when you release.

## [Unreleased]

- Index breakdowns from Michigan's tables 2n to 5b: `betteroff get ICS --by income` (or ICC, ICE) gives the index within income terciles, and `--by age`, `education`, `region` and `party` work the same way. Each also has its own id, such as `consumer_sentiment_by_income`, and works in `describe`, `chart`, recipes (`by = "income"`) and `bo.get('ICS', by='income')`.
- Breakdown rows name the group in `population` (`income:top_third`, `party:democrat`), wide output has one column per group, and sidecars list the groups under `question.groups` with a top-level `population` such as `by_income`. Charts use fixed group colors and fit the axis to the values; `--responses` picks groups by id.
- A new parser reads the shared layout of tables 2n to 5b and fails if the banner, index blocks or group labels change. Validation flags months missing after a breakdown became monthly (`missing_month`) and months without a value for every group (`missing_group_value`).

## [0.5.0] - 2026-10-23

- Inflation expectations: expected price changes over the next 12 months (table 32, `price_expectations`) and the next 5 to 10 years (table 33, `price_expectations_5_years`), parsed from Michigan's distribution-and-summary layout.
- Inflation questions take `--measure median` (the default), `mean`, `summary` (median, mean, 25th and 75th percentiles and interquartile range) or `share` (the distribution brackets). Charts of the summary statistics use a percent axis that can go below zero, and `--responses` picks which statistics to draw.
- Questions can have aliases, such as `inflation_1_year` or `inflation_expectations_5_years`, which work anywhere an id does and count in search.
- Question metadata in sidecars now includes `label` and `aliases`.

## [0.4.0] - 2026-10-13

- Headline indexes: the Index of Consumer Sentiment (`ICS`, `consumer_sentiment`), Index of Current Economic Conditions (`ICC`, `current_conditions`) and Index of Consumer Expectations (`ICE`, `consumer_expectations`), from the CSV files on Michigan's main site. They aren't embargoed, so they include the latest final reading and the mid-month preliminary one.
- Index data has a `preliminary` column, and sidecars give `source.release_status` and `coverage.latest_preliminary`. Charts mark a preliminary latest month with an open dot and a subtitle note. When the final reading arrives, the revision report lists the month under `finalized` with both values instead of warning about a revision.
- `chart --responses` draws only the responses you name, by id or by polarity (`positive,negative`), in charts, recipes (`responses =`) and `ds.chart(responses=...)`. The subtitle lists what's left out, and colors don't change.
- `--monthly/--no-monthly` replaces `--no-raw` for hiding the thin monthly lines behind a rolling average; the recipe key and Python argument are now `monthly`. The old names still work. Chart sidecars record `monthly` and `responses` instead of `raw`.
- `--measure` now defaults to `share` for tables and `index` for headline indexes.
- One-line charts, such as `--measure index` or a single `--responses` choice, now draw at full line width.
- `cache prune` also removes headline index snapshots, which are stored as `.json`.
- Cache manifests now record each snapshot's file type. Older versions can't read them, so to go back to 0.3.0 or earlier, delete the cache directory (`betteroff cache path`).

## [0.3.0] - 2026-10-12

- `betteroff cache prune` deletes older snapshots, keeping the newest per question (`--keep`, default 1) and always the latest; `--dry-run` lists what it would delete.
- Charts use Inter instead of Roboto, still falling back to Helvetica, Arial and sans-serif. Choose another family with `chart --font`, `font =` in recipes, `ds.chart(font=...)` or the `BETTEROFF_FONT` environment variable. Chart sidecars record the font, and the static-export check now looks for whichever font you chose.
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
