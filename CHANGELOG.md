# Changelog

All notable changes to Betteroff. Versions follow [semantic versioning](https://semver.org/). Add entries under Unreleased; `scripts/publish.sh` moves them under a dated version heading when you release.

## [Unreleased]

## [0.1.0] - 2026-10-12

First release.

- Catalog of 18 Surveys of Consumers tables in the historical three-category layout, searchable offline by id, table number, title, keywords and wording.
- `get` fetches, validates and caches Michigan's historical Excel files and exports tidy or wide CSV and JSON with a metadata sidecar. `--measure index` returns Michigan's index score.
- `chart` makes HTML, SVG, PNG, PDF and Vega-Lite charts with polarity colors, direct labels, monthly tooltips, trailing averages, NBER recession shading and explicit gaps for missing months.
- `run` rebuilds declared outputs from a TOML recipe and records the snapshot behind each one.
- Content-addressed snapshots with revision reports; failed or invalid refreshes never replace the last good snapshot.
- Exit codes 2, 3 and 4 for input, fetch and validation failures.
