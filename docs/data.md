# Data, metadata and caching

## Source

Betteroff reads the **historical** Excel file for each table on Michigan's [tables page](https://data.sca.isr.umich.edu/tables.php), the link labeled `RB` in the page's markup. It holds every published reading for the table, one row per survey month. The monthly, quarterly and yearly files on the same page cover shorter periods and aren't used.

Verified in October 2026:

- The files are legacy Excel (`.xls`, OLE2), read with xlrd.
- Each link carries the release year and month and a key: `get-table.php?c=RB&y=2026&m=8&n=34&f=xls&k=...`. The key changes with releases, so Betteroff finds the link on the tables page every time instead of building it.
- A stale or invalid key returns HTTP 200 with the text `Not Found<br/>`. Betteroff checks the Excel file signature and rejects anything else with exit code 3.
- The layout: question wording in the rows above a header row that starts with "Date of Survey," then month name, year, one column per response, `Total`, `Relative` (the index score) and `Cases`.

## When data appears

Michigan publishes a preliminary and a final reading each month at [sca.isr.umich.edu](http://www.sca.isr.umich.edu/). The detailed-data site that Betteroff reads updates after an embargo that ends four weeks after the final release. In October 2026 the latest month available was August 2026.

So Betteroff reports two different times:

- **Latest month** (`coverage.latest_period`): the newest survey month in the file.
- **Retrieved** (`snapshot.retrieved_at`): when Betteroff downloaded these bytes.

A refresh that finds no new month is normal. Betteroff never fills the gap with headline numbers from elsewhere.

## Data contract

Tidy rows, one per month and response:

| Field | Meaning |
| --- | --- |
| `date` | First day of the survey month, ISO date |
| `question_id` | Catalog id, such as `government_policy` |
| `measure` | `share` or `index` |
| `response_id` | Stable id from the catalog, such as `good_job`; `index` for the index score |
| `response_label` | The source's column label, such as `Good Job` or `DK, NA` |
| `value` | Number as published, or null |
| `unit` | `percent` for shares, `index` for the index score |
| `cases` | Interviews that month |
| `population` | `all_households` |

Wide output has one row per month, one column per response id in catalog order, and `cases`.

Betteroff does not round, rescale percentages to fractions, fill missing values with zero or drop categories. An unexpected category stops the run instead.

### The index score

Michigan's index score for each table is the percent giving the favorable answer minus the percent giving the unfavorable answer, plus 100. It runs from 0 to 200, with 100 meaning the two are balanced. Historical files call it "Relative." Use `--measure index` to get it.

### Polarity

The catalog marks each response `positive`, `neutral`, `negative` or `nonresponse`. Positive and negative follow Michigan's index formula, not an editorial view: for interest rates, "go down" is positive; for unemployment, "less" is positive. Polarity sets chart colors so "better" looks the same on every chart.

### Missing months

Before January 1978 the survey was irregular, mostly quarterly. A few questions went monthly later: tables 10 and 11 in July 2011 and table 45 in September 1992. Betteroff keeps every published reading. Charts start at the beginning of monthly data unless you pass `--start`, and they break lines at months with no reading rather than drawing across them.

## Metadata sidecar

Every file written with `-o`, by a recipe, or by `--meta` gets JSON metadata. A file named `gov.csv` gets `gov.csv.meta.json`.

| Key | Contents |
| --- | --- |
| `schema_version` | Metadata format version, now 1 |
| `betteroff_version`, `parser_version` | Software that made the file |
| `question` | Id, table, title, exact wording, responses with source labels and polarity, notes, breaks, index definition |
| `population`, `units` | `all_households`; `percent` and `index` |
| `source` | Publisher, tables page, download URL, table, release period in the link, `release_status` (`unknown`: the file doesn't say whether readings are preliminary or final), usage agreement URL |
| `snapshot` | Short id, SHA-256 of the raw file, retrieval and last-check times in UTC, and `mode`: `fresh`, `cached`, `stale` or `offline` |
| `coverage` | First and latest survey month, number of readings, start of monthly data |
| `notes` | Methodology notes from the catalog |
| `source_notes` | Notes printed in the source file |
| `quality_flags` | Known inconsistencies in the source (see below) |
| `revisions` | What changed since the previous snapshot, when this run fetched new bytes |
| `export` | File name, format, measure, date range and chart options |

## Validation

These stop the run with exit code 4 and leave the cache untouched:

- Headers that don't exactly match the catalog's response labels, plus `Total`, `Relative` and `Cases`
- A row whose date can't be read, a month listed twice, or a value that isn't a number or blank
- A share outside 0 to 100, an index outside 0 to 200, or a case count of zero or less
- A latest month in the future, or a response with no values at all

These are recorded in `quality_flags` and don't stop the run, because Michigan's own files contain a handful of them:

- `shares_do_not_sum_to_total`: responses differ from the stated total by more than 1 point
- `index_does_not_match_shares`: the index differs from favorable minus unfavorable plus 100 by more than 1
- `total_not_100`
- `wording_changed`: the wording in the file no longer matches the catalog; this also raises a warning

In October 2026, seven of the 18 tables had between one and four flagged months, all before 1984.

## Cache

`betteroff cache path` prints the location; `BETTEROFF_CACHE_DIR` overrides it.

```text
cache/
  manifest.json          latest snapshot and history per question
  manifest.lock          present only while a process updates the manifest
  snapshots/<sha256>.xls raw downloads, named by content hash
```

- A snapshot checked in the past 24 hours is reused. Otherwise Betteroff checks the source.
- If that automatic check fails, Betteroff uses the saved snapshot and warns. If `--refresh` fails, the command fails.
- New bytes are parsed and validated before they're saved. A failed download, an access page or a schema mismatch never replaces the latest snapshot.
- Snapshots are kept by hash, so a refresh never deletes the file behind earlier work. The manifest records every snapshot; `cache info` shows how many each question has. `cache prune` deletes older ones when you ask it to. Picking an older snapshot isn't available yet.
- Processes sharing a cache, such as two recipe runs, take turns updating the manifest through `manifest.lock`. A lock older than 30 seconds is treated as left over from a crash and removed.
- Betteroff can't recover versions published before it started saving them.

### Revisions

When new bytes arrive, Betteroff compares them with the previous snapshot and records:

```json
"revisions": {
  "appended_months": ["2026-08"],
  "removed_months": [],
  "changed_months": [],
  "changed_values": 0,
  "previous_snapshot": "1ec010d3b0d2"
}
```

New months are a notice. Changed or removed months are a warning, which `--quiet` doesn't hide.

## Adding a table

1. Download the table's historical Excel file from the tables page and read the header row and the wording above it. Don't commit the file.
2. Add a `[[questions]]` entry to `src/betteroff/data/catalog.toml` with an id, the table number, a sentence-case title, the wording copied exactly and each response's `source_label` exactly as the file has it. Set polarity from the index formula: the response that's added is `positive`, the one subtracted is `negative`.
3. Add `notes`, `monthly_since` or `breaks` if the question changed or wasn't asked monthly.
4. Run `uv run pytest -m live -k <table>` to parse it, validate it and compare the first, middle and last rows with the raw file.
