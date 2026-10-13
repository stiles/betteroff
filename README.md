# Betteroff

Clean data and charts from the Michigan consumer surveys.

Betteroff finds, downloads, validates, exports and charts the published monthly tables from the University of Michigan [Surveys of Consumers](https://data.sca.isr.umich.edu/). It keeps the question wording, response labels and source details attached to every file it writes, so a CSV or chart can be traced back to the exact download behind it.

```bash
betteroff search government
betteroff get government_policy --wide -o government_policy.csv
betteroff chart government_policy --rolling 12 --recessions -o government_policy.svg
```

Betteroff is an independent project. It is not affiliated with or endorsed by the University of Michigan. See [Data use](#data-use) before publishing anything made with it.

## Install

Betteroff needs Python 3.11 or newer. The charts are an optional extra because they pull in Altair and vl-convert.

```bash
# Command-line tool in its own environment, with charts
uv tool install 'betteroff[charts]'

# Try it without installing
uvx betteroff search housing
uvx --from 'betteroff[charts]' betteroff chart 41

# Python library in an analysis project or notebook environment
uv add 'betteroff[charts]'
```

`pip install 'betteroff[charts]'` works too. A `uv tool` install doesn't make the module importable in a notebook; add it to the notebook's project for that.

## Quick start

Find a question. Search and list work offline because they read only the packaged catalog.

```console
$ betteroff search unemployment
Table  Id                           Title
   30  unemployment_expectations    Expected change in unemployment during the next year
   29  business_conditions_5_years  Business conditions expected during the next 5 years
   34  government_policy            Opinions about the government's economic policy
```

Read the question's wording, response categories and notes. Once data is cached, `describe` also shows the latest three months and a 24-month sparkline per response.

```bash
betteroff describe unemployment_expectations
```

Get the data. In a terminal you see the latest 24 months; piped or written to a file you get every month.

```bash
betteroff get 30                                   # table in the terminal
betteroff get 30 > unemployment.csv                # tidy CSV, one row per month and response
betteroff get 30 --wide -o unemployment_wide.csv   # one row per month, for Datawrapper
betteroff get 30 --measure index -f json           # Michigan's index score as JSON records
```

Chart it.

```bash
betteroff chart 30 --open                                   # unemployment_expectations.html
betteroff chart 30 --rolling 12 --recessions -o unemp.svg   # editable vector file
betteroff chart 30 --start 2000 -o unemp.png                # 2x PNG
betteroff chart 30 --theme brbg -o unemp_brbg.html          # another color theme
```

Favorable and unfavorable answers get the theme's two colors on every chart; neutral answers are gray and nonresponse a dashed light gray. `betteroff themes` lists the color themes with swatches; the default is `okabe-ito`, a colorblind-safe blue and vermillion.

Table numbers and ids are interchangeable: `betteroff get 34` and `betteroff get government_policy` return the same data.

## Python

```python
import betteroff as bo

bo.search('housing')
ds = bo.get('government_policy', refresh=True)
ds.data          # tidy pandas DataFrame
ds.wide()        # one row per month
ds.metadata      # wording, source, snapshot, coverage, notes
chart = ds.chart(rolling=12, recessions=True)   # a plain altair.LayerChart
chart.save('government_policy.html', inline=True)
```

See the [Python API docs](https://github.com/stiles/betteroff/blob/main/docs/python.md).

## Supported tables

Every table in Michigan's catalog that uses the historical three-category layout, with one positive, one neutral and one negative response plus nonresponse where reported:

| Table | Id | Title |
| --- | --- | --- |
| 6 | `current_finances` | Current financial situation compared with a year ago |
| 8 | `expected_finances` | Expected change in financial situation in a year |
| 10 | `finances_vs_5_years_ago` | Current financial situation compared with 5 years ago |
| 11 | `expected_finances_5_years` | Expected change in financial situation in 5 years |
| 14 | `real_income_expectations` | Expected change in real household income during the next year |
| 19 | `retirement_chances` | Change in likelihood of comfortable retirement |
| 25 | `business_conditions_vs_year_ago` | Current business conditions compared with a year ago |
| 26 | `business_conditions_expected` | Expected change in business conditions in a year |
| 28 | `business_conditions_12_months` | Business conditions expected during the next year |
| 29 | `business_conditions_5_years` | Business conditions expected during the next 5 years |
| 30 | `unemployment_expectations` | Expected change in unemployment during the next year |
| 31 | `interest_rate_expectations` | Expected change in interest rates during the next year |
| 34 | `government_policy` | Opinions about the government's economic policy |
| 35 | `durables_buying_conditions` | Buying conditions for large household durables |
| 37 | `vehicle_buying_conditions` | Buying conditions for vehicles |
| 41 | `home_buying_conditions` | Buying conditions for houses |
| 43 | `home_selling_conditions` | Selling conditions for houses |
| 45 | `home_value_change` | Change in home values during the past year |

Tables with other layouts (the sentiment indexes, income and price distributions, probabilities, reasons for opinions and demographic breakdowns) aren't supported yet. All series cover all households.

## How it works

1. Betteroff reads Michigan's [tables page](https://data.sca.isr.umich.edu/tables.php), finds the current link to the table's historical Excel file and downloads it. Links carry a per-release key, so they are discovered fresh instead of guessed.
2. It checks the file is a real Excel workbook, not an access page or error text sent with HTTP 200, then parses it and checks the column headers against the catalog. Any unexpected or missing column stops the run with exit code 4.
3. It validates the values and saves the raw bytes in a content-addressed cache with a manifest. A failed download or validation never replaces the last good snapshot.
4. Later runs reuse the cache for 24 hours. `--refresh` forces a check; `--offline` never touches the network.
5. When a refresh brings new bytes, Betteroff compares them with the previous snapshot and reports new months, revised months and removed months.

**Latest month is not the same as retrieval time.** Michigan's detailed-data site updates after an embargo that ends four weeks after each month's final release, so the newest month here trails the headline number by a month or more. A refresh that finds no new month is working as intended.

More in the [data docs](https://github.com/stiles/betteroff/blob/main/docs/data.md).

## Outputs

| Command | Output |
| --- | --- |
| `get` in a terminal | Latest 24 months as a table |
| `get` piped | Tidy CSV on stdout; notices on stderr |
| `get -o FILE.csv` or `.json` | Tidy file, or wide with `--wide`, plus `FILE.csv.meta.json` |
| `chart -o FILE.html` | Self-contained HTML that works offline |
| `chart -o FILE.svg`, `.png`, `.pdf` | 16:9 static files; SVG text stays editable |
| `chart -o FILE.vl.json` | Vega-Lite spec with inline data for the Vega Editor or vega-embed |
| `run betteroff.toml` | Every output the recipe declares, plus `betteroff-run.json` |

Every file gets a metadata sidecar with the question wording, response mapping, source URL, retrieval time, snapshot hash, coverage, notes, source quirks and package versions. Betteroff refuses to overwrite a file unless you pass `--force`.

## Recipes

Save a workflow in TOML and rerun it with one command:

```toml
schema_version = 1
output_dir = 'output'

[[jobs]]
question = 'government_policy'
start = '2000-01-01'
data_formats = ['csv', 'json']
chart_formats = ['html', 'svg']
rolling = 12
recessions = true
```

```bash
betteroff run betteroff.toml --refresh
```

See the [recipe docs](https://github.com/stiles/betteroff/blob/main/docs/recipes.md).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 2 | Invalid input: unknown id, bad option, format conflict, file exists |
| 3 | Fetch or access failure, or `--offline` with no saved snapshot |
| 4 | The source file no longer matches what the parser expects |

Errors print one line and a suggested fix. Add `--debug` before the command, or set `BETTEROFF_DEBUG=1`, for a full traceback.

## Environment

| Variable | Effect |
| --- | --- |
| `BETTEROFF_CACHE_DIR` | Cache location; defaults to the platform cache directory (`betteroff cache path`) |
| `BETTEROFF_DEBUG` | Show tracebacks |
| `NO_COLOR` | Disable color |

## Data use

Michigan's [usage agreement](https://data.sca.isr.umich.edu/agreement.php) lets you display, reformat and print the data for your organization's use with the attribution "University of Michigan, Survey Research Center, Surveys of Consumers." It bars reproducing, redistributing, publishing or broadcasting the data without written consent from the university.

Betteroff's MIT license covers the code only, not the data. Betteroff fetches data to your machine and never hosts or bundles it. Its tests use synthetic files. Getting permission for any publication is up to you; charts include the required attribution in their footer.

## Documentation

- [Command-line reference](https://github.com/stiles/betteroff/blob/main/docs/cli.md)
- [Python API](https://github.com/stiles/betteroff/blob/main/docs/python.md)
- [Data, metadata and caching](https://github.com/stiles/betteroff/blob/main/docs/data.md)
- [Charts](https://github.com/stiles/betteroff/blob/main/docs/charts.md)
- [Recipes](https://github.com/stiles/betteroff/blob/main/docs/recipes.md)
- [Releasing](https://github.com/stiles/betteroff/blob/main/docs/releasing.md)
- [Changelog](https://github.com/stiles/betteroff/blob/main/CHANGELOG.md)

## Development

```bash
git clone https://github.com/stiles/betteroff && cd betteroff
uv sync --all-extras
uv run pytest                # offline tests
uv run pytest -m live        # fetch every table from Michigan; run sparingly
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy
```

Normal tests never touch the network. A scheduled GitHub Action runs the live check weekly and opens an issue if Michigan's files change.

## License

MIT for the code. The data belongs to the University of Michigan; see [Data use](#data-use).
