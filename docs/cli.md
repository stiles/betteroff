# Command-line reference

Every command accepts `-h` or `--help`. Global options go before the command:

```bash
betteroff --version
betteroff --debug get 34      # full traceback on error; or set BETTEROFF_DEBUG=1
```

Shell completion: `betteroff --install-completion` for your current shell, or `--show-completion` to print the script.

## Identifiers

Every command that takes a question accepts its id (`government_policy`), its published table number (`34`) or `"table 34"`. The table number is Michigan's table identifier, not a question number in the questionnaire. A near-miss suggests the closest ids.

## `search TEXT`

Searches ids, titles, keywords, question wording and response labels. Every word must match. Works offline.

```bash
betteroff search housing
betteroff search "interest rates"
```

In a terminal the results are a table. Piped, each result is a tab-separated line: `table`, `id`, `title`.

## `list`

Lists every supported table in the same format as `search`.

## `describe ID`

Shows the title, table, exact question wording, response ids, labels, source labels, polarity, units, the index definition, notes and usage terms.

If the question has a cached snapshot, it adds the latest three months and a 24-month sparkline for each response, with the range the sparkline spans. It never fetches.

| Option | Effect |
| --- | --- |
| `--json` | Print the catalog entry as JSON |

## `get ID`

Fetches the table, or reuses the cache, validates it and prints or writes it.

| Option | Effect |
| --- | --- |
| `-o, --output FILE` | Write `.csv` or `.json`, plus `FILE.meta.json` |
| `-f, --format table\|csv\|json` | Override the format. Must agree with the `-o` extension |
| `--wide` | One row per month, one column per response id |
| `-m, --measure share\|index` | Response shares in percent (default) or the index score |
| `--start`, `--end` | Limit months; `YYYY`, `YYYY-MM` or `YYYY-MM-DD` |
| `--refresh` | Check the source now, even if the cache is fresh |
| `--offline` | Use the saved snapshot only; fail if there is none |
| `--meta FILE` | When printing to stdout, also write metadata to `FILE` |
| `--force` | Overwrite existing files |
| `-q, --quiet` | Hide notices; keep warnings that change what the data means |

Without `--format`, `get` prints a table when stdout is a terminal and CSV when it's piped. The terminal table shows the latest 24 months of the selected range; use `-o` or a pipe for everything.

Tidy output, the default:

```csv
date,question_id,measure,response_id,response_label,value,unit,cases,population
2026-08-01,government_policy,share,good_job,Good Job,12,percent,1073,all_households
```

Wide output with `--wide`:

```csv
date,good_job,fair,poor_job,dk_na,cases
2026-08-01,12,14,74,0,1073
```

Wide headers are response ids in catalog order, so they stay stable across releases. Labels are in the sidecar. JSON output is a list of records with the same fields.

## `chart ID`

Builds a chart from the same validated data `get` returns. Needs the `charts` extra.

| Option | Effect |
| --- | --- |
| `-o, --output FILE` | `.html`, `.svg`, `.png`, `.pdf` or `.vl.json`. Defaults to `ID.html` in the current directory |
| `-f, --format` | Override the format. Must agree with the `-o` extension |
| `--rolling N` | Trailing average over N calendar months |
| `--no-raw` | Hide the thin monthly lines drawn behind a rolling average |
| `--recessions` | Shade NBER recessions |
| `-m, --measure share\|index` | Response shares (default) or the index score |
| `--start`, `--end` | Displayed range. Defaults to the start of monthly data, usually January 1978 |
| `--width`, `--height` | Frame size in pixels for static output. Default 960 by 540 |
| `-t, --theme NAME\|FILE` | Color theme: `okabe-ito` (default), `puor`, `brbg`, `rdbu`, `tol` or a `.toml` file |
| `--font FAMILY` | Font family for chart text, such as `"IBM Plex Sans"`. Defaults to `BETTEROFF_FONT`, then Inter |
| `--refresh`, `--offline` | As for `get` |
| `--open` | Open the file in a browser |
| `--force` | Overwrite existing files |
| `-q, --quiet` | As for `get` |

HTML fills the width of its container unless you pass `--width`. An unknown theme or a font value that isn't a single family name fails before anything is fetched. See [charts.md](charts.md).

## `themes`

Lists the packaged color themes with swatches for the positive, neutral, negative and nonresponse colors, and marks the default. Piped, each theme is a tab-separated line: `name`, `positive`, `negative`, `description`. Works offline.

## `run FILE`

Runs a TOML recipe. See [recipes.md](recipes.md).

| Option | Effect |
| --- | --- |
| `--refresh`, `--offline` | Applied to every question in the recipe |
| `-q, --quiet` | Hide notices |

## `cache info`

Lists each cached question with its latest survey month, retrieval time, last check, snapshot id and the number of snapshots kept. Tab-separated when piped.

## `cache prune`

Deletes older snapshots, keeping the newest per question, plus any snapshot files the manifest doesn't list. The latest snapshot for each question is always kept. Prints each deleted path on stdout and a summary on stderr. Sidecars written from a pruned snapshot still record its hash, but the raw file behind them is gone.

| Option | Effect |
| --- | --- |
| `--keep N` | Snapshots to keep per question; default 1 |
| `--dry-run` | List what would be deleted without deleting it |

## `cache path`

Prints the cache directory. Set `BETTEROFF_CACHE_DIR` to move it, for example in CI or on a shared machine.

## Streams and exit codes

Data goes to stdout and nothing else does. Retrieval notices, written-file notices and warnings go to stderr. `--quiet` drops notices but keeps warnings that change what the data means: an offline or stale snapshot, revised history or a changed question wording.

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 2 | Invalid input, including an existing output file without `--force` |
| 3 | Fetch or access failure, or `--offline` with no snapshot |
| 4 | Source file failed validation |

`--refresh` and `--offline` together are an input error.
