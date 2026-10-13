# Data, metadata and caching

## Source

Betteroff reads the **historical** Excel file for each table on Michigan's [tables page](https://data.sca.isr.umich.edu/tables.php), the link labeled `RB` in the page's markup. It holds every published reading for the table, one row per survey month. The monthly, quarterly and yearly files on the same page cover shorter periods and aren't used.

Verified in October 2026:

- The files are legacy Excel (`.xls`, OLE2), read with xlrd.
- Each link carries the release year and month and a key: `get-table.php?c=RB&y=2026&m=8&n=34&f=xls&k=...`. The key changes with releases, so Betteroff finds the link on the tables page every time instead of building it.
- A stale or invalid key returns HTTP 200 with the text `Not Found<br/>`. Betteroff checks the Excel file signature and rejects anything else with exit code 3.
- The layout: question wording in the rows above a header row that starts with "Date of Survey," then month name, year, one column per response, `Total`, `Relative` (the index score) and `Cases`.

## Headline indexes

The three headline indexes (ICS, ICC and ICE) come from CSV files on Michigan's [main site](https://www.sca.isr.umich.edu/tables.html) instead, because those aren't embargoed. Verified in October 2026, each index joins two files:

| Index | History file | Current file |
| --- | --- | --- |
| ICS | `tbmics.csv`, column `ICS_ALL` | `tbcics.csv`, column `INDEX OF CONSUMER SENTIMENT` |
| ICC | `tbmiccice.csv`, column `ICC` | `tbciccice.csv`, column `CURRENT INDEX` |
| ICE | `tbmiccice.csv`, column `ICE` | `tbciccice.csv`, column `EXPECTED INDEX` |

- The history file has every final reading, one row per survey month, under a `Month,YYYY` header.
- The current file has a title, a `DATE OF SURVEY` header, the last 12 months and, after Michigan's mid-month release, the new preliminary reading with `(P)` after the month name, such as `October (P),2026`.
- Betteroff takes final readings from the history file and adds what the current file has beyond it: a final reading the history file doesn't have yet, and the preliminary reading. When both files list a month, the history file wins; if their values differ, the month gets a `current_file_differs` quality flag.
- The weekly live check compares every final reading with the data site's historical tables 1a and 1b.

The two files are cached together as one snapshot, a JSON file keyed by URL.

Michigan's main site states only its copyright. Its tables carry the same data as the detailed-data site, whose [usage agreement](https://data.sca.isr.umich.edu/agreement.php) is the closest statement of terms; see [Data use](../README.md#data-use).

### Preliminary readings

Michigan releases a preliminary reading in the middle of each month, from about 420 interviews, and a final reading at the end of the month from about 1,000. Newsrooms cite the preliminary reading because it's the newest, so Betteroff includes it and labels it:

- Every row of index data has a `preliminary` column, `true` only for the preliminary month.
- The sidecar's `source.release_status` is `preliminary` or `final` for the latest month, and `coverage.latest_preliminary` is a plain true or false for front ends deciding whether to add a note.
- Charts draw a preliminary latest month as an open dot and say so in the subtitle. Tooltips give each month's release.
- When the final reading arrives, the revision report lists the month under `finalized` with both values, as a notice rather than a warning.

## When data appears

Michigan publishes a preliminary and a final reading each month at [sca.isr.umich.edu](http://www.sca.isr.umich.edu/). The headline indexes are current. The detailed-data site that Betteroff reads for tables updates after an embargo that ends four weeks after the final release. In October 2026 the latest month available was August 2026.

So Betteroff reports two different times:

- **Latest month** (`coverage.latest_period`): the newest survey month in the file.
- **Retrieved** (`snapshot.retrieved_at`): when Betteroff downloaded these bytes.

A refresh that finds no new month is normal. Betteroff never fills a table's gap with numbers from elsewhere.

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

Headline indexes have the same tidy fields with `measure` and `response_id` set to `index`, `response_label` set to the index's title and `unit` set to `index`. They have no `cases`, since Michigan's files don't give them, and add `preliminary`, true or false. Wide output is `date`, `index` and `preliminary`. Index values use a 1966 base period (1966 = 100).

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
| `source` | Publisher, tables page, download URL, table, release period in the link, `release_status` (`unknown`: the file doesn't say whether readings are preliminary or final), usage agreement URL. For a headline index: the main site's tables page, both `download_urls`, the `code` and `release_status` `preliminary` or `final` |
| `snapshot` | Short id, SHA-256 of the raw file, retrieval and last-check times in UTC, and `mode`: `fresh`, `cached`, `stale` or `offline` |
| `coverage` | First and latest survey month, number of readings, start of monthly data and, for a headline index, `latest_preliminary` |
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
  snapshots/<sha256>.xls raw table downloads, named by content hash
  snapshots/<sha256>.json headline index CSV files, bundled
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

For a headline index, a month that was preliminary and is now final isn't a revision. It's listed under `finalized` with both values, and Betteroff logs a notice such as `consumer_sentiment: 2026-10 is now final at 47.0 (preliminary was 46.3)`:

```json
"finalized": [{"month": "2026-10", "preliminary": 46.3, "final": 47.0}]
```

## Adding a table

1. Download the table's historical Excel file from the tables page and read the header row and the wording above it. Don't commit the file.
2. Add a `[[questions]]` entry to `src/betteroff/data/catalog.toml` with an id, the table number, a sentence-case title, the wording copied exactly and each response's `source_label` exactly as the file has it. Set polarity from the index formula: the response that's added is `positive`, the one subtracted is `negative`.
3. Add `notes`, `monthly_since` or `breaks` if the question changed or wasn't asked monthly.
4. Run `uv run pytest -m live -k <table>` to parse it, validate it and compare the first, middle and last rows with the raw file.
