# Betteroff: project and implementation plan

Working proposal · October 12, 2026

## Product

Betteroff helps journalists and researchers find, refresh, export and chart published responses from the University of Michigan Surveys of Consumers. It removes the repeated work of locating tables, downloading files and cleaning headers while keeping the source question and measurement context attached.

The first release covers published monthly aggregate tables. Individual respondent microdata, additional survey providers and custom weighted estimates are outside its initial scope.

Success: a returning user can update a previously used series and recreate an exploratory chart with one familiar command, without opening the source website or editing a notebook.

## Name and identity

Decided: **Betteroff**, with the subtitle **Clean data and charts from the Michigan consumer surveys**.

| Surface | Name |
| --- | --- |
| Project | Betteroff |
| Repository, Python distribution, import and command | `betteroff` |

The name comes from the survey's best-known question: whether a household is better or worse off financially than a year ago. Anyone who covers the economy will recognize it, and it doesn't borrow the university's name. It reads naturally as a command (`betteroff get government_policy`), has nine letters and no hyphen, so the distribution, import and command can be identical. Avoid an additional abbreviated command in v0.1.

Known tradeoffs: the name echoes Reagan's 1980 "better off" line, and the catalog covers more than personal finances. Neither outweighs the recognition.

Also considered: SurveyGlass (the working name), `kitchentable`, `surveysays`, `pursestrings` and `umcsent`. Avoid names containing Michigan, UMich, Wolverine or "Surveys of Consumers," which could read as an official product.

`betteroff` and `better-off` were unclaimed on PyPI on October 12, 2026, but nothing is reserved yet. Claim the PyPI name and GitHub repository early, then check similar projects and trademark conflicts before launch. GitHub already has unrelated repositories named `betteroff`. State that the project is independent and is not an official University of Michigan product.

## Guiding principles

- Clean data is the core product; charts help users inspect it quickly.
- One implementation serves the CLI and Python API.
- Keep original values, labels, question wording and provenance available.
- Prefer a small, explicit catalog over guessing how arbitrary spreadsheets work.
- Fail visibly when the source changes in a way the parser cannot explain.
- Make automation predictable: clean stdout, useful exit codes and no required prompts.

## Proposed user experience

All Betteroff commands and Python calls below are proposed interfaces, not working software. Installation examples apply after publication.

```bash
# Install the CLI in its own environment
uv tool install 'betteroff[charts]'

# Find and understand a question
betteroff search government
betteroff describe government_policy

# Read data in the terminal or export it
betteroff get government_policy
betteroff get government_policy --wide -o government_policy.csv
betteroff get 34 --format json > government_policy.json

# Refresh from the source and produce a chart
betteroff chart government_policy --refresh -o government_policy.html
betteroff chart government_policy --rolling 12 --recessions -o government_policy.svg
betteroff chart government_policy -o government_policy.vl.json

# Repeat a recorded workflow
betteroff run betteroff.toml --refresh
```

Table 34 resolves to the same catalog entry as `government_policy`. Treat 34 as a published table identifier, not necessarily the questionnaire's question number.

Because the package and command share a name, `uvx betteroff search government` works as a no-install trial; charts need `uvx --from 'betteroff[charts]' betteroff chart ...`. Python users install into their analysis project with `uv add betteroff`; a tool installation does not make the module available in a notebook's environment.

### Command contract

| Command | Behavior |
| --- | --- |
| `search TEXT` | Search titles, documented wording and catalog keywords; no network needed |
| `list` | Show supported tables and identifiers |
| `describe ID` | Show wording, source table, units, ordered response categories, notes and access limitations. If a validated snapshot is cached, add the latest three months and a 24-month sparkline per response |
| `get ID` | Fetch or reuse cache, validate and return normalized observations |
| `chart ID` | Use the same data path and create an exploratory chart |
| `run FILE` | Reproduce exports and charts from a TOML recipe |
| `cache info` | Show cached sources, retrieval times and latest observation periods |
| `cache path` | Print the cache directory, for scripts and CI |

Shared data options: `--start`, `--end`, `--refresh` and `--offline`. `--refresh` forces a source check; `--offline` requires an existing validated snapshot. Reject using both together.

### Output rules

- `get` without `--format` prints a compact Rich table when stdout is a terminal and CSV when it is piped. `--format table|csv|json` overrides. JSON uses records.
- `-o/--output` infers the format from the extension: `.csv` and `.json` for `get`; `.html`, `.svg`, `.png`, `.pdf` and `.vl.json` for `chart`. A `--format` that contradicts the extension is an input error.
- Exports are tidy by default. `--wide` gives one row per month and one column per response, in catalog order, headed by `response_id` so headers stay stable across releases. Labels live in the sidecar.
- Every file written with `-o` gets a `NAME.meta.json` sidecar. Stdout exports skip it unless `--meta FILE` is given.
- Logs, retrieval notices and warnings go to stderr. `-q/--quiet` drops notices but keeps warnings that change what the data means, such as an offline snapshot being used or revisions being detected.
- Respect `NO_COLOR`. `BETTEROFF_CACHE_DIR` overrides the platformdirs location for CI and shared machines. No global config file in v0.1; persistent settings belong in recipes.

### CLI implementation notes

- Keep `--help`, completion, `search`, `list` and data-free `describe` fast: they read only the packaged catalog. Import pandas, HTTPX and Altair inside the commands that need them, and test that `search` loads none of them.
- Create the Typer app with `pretty_exceptions_enable=False`. One top-level handler maps the package's exception classes to exit codes and prints a one-line message with a corrective action. `--debug` or `BETTEROFF_DEBUG=1` re-raises for a full traceback.
- Click already exits 2 on usage errors, which matches the contract below. Provide shell completion and examples in help.

Use exit code 0 for success, 2 for invalid input, 3 for fetch/access failures and 4 for schema/validation failures. Include a corrective action in errors. Refuse to overwrite an explicit output path unless `--force` is supplied; recipe runs may replace only their declared outputs.

### Python API

```python
import betteroff as bo

bo.search('government')
dataset = bo.get('government_policy', refresh=True)
df = dataset.data
metadata = dataset.metadata
chart = dataset.chart(rolling=12, recessions=True)  # an altair.Chart
chart.save('government_policy.html')
```

Return a small Dataset object holding a pandas DataFrame and structured metadata. Do not subclass pandas or hide metadata solely in DataFrame attributes. `dataset.chart()` returns a plain Altair chart so notebook users can display it inline, layer on it or change its properties. Keep chart dependencies optional; give a clear installation instruction if they are missing.

## Technology choices

| Layer | Choice | Reason |
| --- | --- | --- |
| Project and tool installation | uv, `pyproject.toml`, committed `uv.lock` | Consistent development setup and isolated CLI installation |
| Language | Python 3.11+ | `tomllib` in the standard library reads the catalog and recipes |
| CLI | Typer, tested with Click's `CliRunner` | Typed arguments, help and shell completion; Click's usage-error exit code matches the contract |
| Terminal display | Rich | Tables, Unicode sparklines and a stderr console for notices; no terminal plotting library |
| HTTP | HTTPX, synchronous client | Explicit timeouts, reusable connections and testable transport |
| Parsing | pandas and source-specific Excel engine; BeautifulSoup when needed | Familiar analysis workflow with explicit handling of source layouts |
| Models | Standard-library dataclasses | Small metadata contract without another framework |
| Cache/config paths | platformdirs; JSON manifests and local files | Works across macOS, Linux and Windows without a database service |
| Charts extra | Altair 6 and vl-convert-python | Vega-Lite specs from Python; offline HTML, SVG, PNG and PDF with no browser or Node.js |
| Developer checks | Ruff, pytest and mypy | Formatting, correctness and typed public interfaces |
| Automation | GitHub Actions | Offline tests on changes and a separate low-frequency live-source check |

Select the Excel engine after inspecting actual downloads; file suffixes can be misleading. Add openpyxl for genuine XLSX and xlrd only if legacy XLS is required. These series are small enough that pandas is sufficient. No database, asynchronous crawler or full-screen terminal UI is needed initially.

Why Altair: a chart is a declarative Vega-Lite spec. That makes it testable as a dictionary, portable to the Vega Editor or a web page through vega-embed, and exportable without a browser. Plotly's static export depends on a local Chrome through Kaleido, which is fragile in uv tool environments and CI. Matplotlib has no interactive output. vl-convert 2.0 is still in release candidates; pin `vl-convert-python>=1.9,<2` and test the upgrade once 2.0 is final.

## Source discovery comes first

The website lists detailed tables, Excel downloads and a time-series query interface. The precise download routes, query parameters and file layouts have not yet been tested for this project. Do not treat the interface as a documented API.

Start with table 34 and verify:

1. Which public download contains the full historical response shares, rather than only a net index or recent periods?
2. Whether the time-series interface or historical table download is the more stable source.
3. Actual response labels, date coverage, missing-value conventions, footnotes and units.
4. How URLs and files change with a monthly release.
5. Whether redirects lead to an access page instead of data.

Then inspect four contrasting candidates: current household finances, expected household finances, unemployment expectations and durable-goods buying conditions. Final inclusion depends on public availability and successful validation.

Michigan's FAQ states that the detailed data site updates after an embargo ending four weeks after the month's final release. Show latest observation period separately from retrieval time. A successful refresh may return no newer observations; do not label that as a failed update or imply access to the newest headline release.

The published usage agreement restricts redistribution and publication without written consent. Resolve intended distribution and publication uses with Michigan before offering hosted data downloads or bundling source data into a public repository. An open-source code license does not license the underlying data. A local-fetch architecture reduces the need for a mirror but does not itself resolve these terms. This is a specific launch dependency, not a reason to delay writing the software plan.

## Data and metadata contract

Use tidy observations internally:

| Field | Meaning |
| --- | --- |
| `date` | First day of the monthly reference period, ISO date |
| `question_id` | Stable project identifier such as `government_policy` |
| `response_id` | Stable response identifier, mapped from verified source labels |
| `response_label` | Source response label |
| `value` | Numeric value or null |
| `unit` | Explicit measure, such as percent or index points |
| `population` | Initially all households |

Keep metadata in a sidecar for exports: title, exact verified question wording, table identifier, response mapping, source URL, retrieval time in UTC, reference coverage, source release date/status when supplied, raw-content hash, parser version, package version, schema version and methodological notes. Unknown release status stays unknown.

Provide wide CSV output for Datawrapper: one row per month and one column per response. Preserve unrounded source precision in data exports. Do not coerce percentages to fractions, substitute zero for missing data or silently drop unrecognized categories.

The catalog also fixes each response's display order and polarity: positive, neutral, negative or nonresponse. Order drives wide-export columns and chart legends; polarity drives chart colors.

Validate unique observation keys, date parsing, expected response categories and numeric ranges appropriate to the measure. Check totals only when documented categories are exhaustive and mutually exclusive, with rounding tolerance. Three visible categories need not sum to 100 if nonresponses are omitted.

## Fetching, caching and revisions

Use explicit timeouts and bounded retries for transient failures, respecting Retry-After. Fetch one source at a time initially. Discover links from the catalog's verified landing page rather than guessing the next document identifier.

Cache raw bytes and validated normalized data with a manifest. Default cache freshness: 24 hours. On expiry, check the source, using HTTP validators when available. Reject an unexpected login page, wrong file signature or schema mismatch before changing the latest cache pointer.

A requested refresh that fails must fail; it must not silently export old data. Users can explicitly choose `--offline` for a saved snapshot. Record the snapshot identity in every file export or chart sidecar.

Retain content-addressed snapshots so a refresh cannot destroy the input behind earlier work. Compare both new months and revised historical values. Report appended, changed and removed observations. Later add cache pruning and snapshot selection; do not promise historical vintages from before the tool began saving them.

## Chart behavior

One function builds every chart from a validated Dataset and options and returns an Altair chart; the CLI, Python API and recipes all call it. Do the data work in pandas before building the spec: calendar reindexing, rolling means and date trimming. The chart then plots exactly the frame users can export, and each transform is tested once in Python instead of again in Vega-Lite expressions.

### Defaults

- Monthly lines, one per response, in catalog order. Colors follow polarity, so "better" is the same color on every chart and colors don't shift when a category is absent. Use a colorblind-safe positive/negative pair, never red against green, a mid-tone for neutral and gray for nonresponse.
- Label lines directly at their latest value instead of using a legend. Use a legend for tables with more than four responses, where end labels collide.
- One hover tooltip per month: a vertical rule at the nearest month listing every response's value with its unit.
- Shares on a 0–100 y-axis with the percent sign on the top tick only. Indices and other measures use domains defined in the catalog. No axis title where ticks make the unit obvious.
- Sentence-case title from the catalog; a subtitle stating the unit and any transformation, such as "12-month trailing average"; a footer with source, table number, latest reference month and retrieval date. No editorial headline or causal claim.
- Full history by default. `--start` and `--end` trim the display after transforms are computed.
- Static exports use a fixed 16:9 frame, overridable with `--width` and `--height`. HTML fills its container's width.

### Missing months and breaks

Reindex to complete calendar months with explicit nulls. A month with no row would otherwise be connected silently. Then set the line mark's `invalid` mode to break paths explicitly instead of relying on Vega-Lite's default, which has changed between versions. Catalog-documented methodological breaks render as a dashed rule with a short label, and lines break there unless the catalog records that the series is comparable across it.

### Rolling averages

`--rolling 12` means a trailing mean of 12 consecutive monthly observations, requiring all 12 values. Reindex to calendar months first so missing months cannot turn it into a misleading 12-observation average. Compute before trimming the displayed date range. Draw the raw monthly values as thin, light lines behind the averages so smoothing doesn't hide volatility; `--no-raw` hides them. The tooltip shows both. Label the transformation and keep raw data available; do not replace the underlying export with smoothed values.

### Recession shading

`--recessions` shades NBER recessions from peak month to trough month, using a small packaged list of dates. The sidecar records the list's source and when it was last checked. Off by default. A test pins the list so any update is a deliberate change.

### Styling and fonts

Apply styling as chart-level config inside the build function rather than enabling a global Altair theme, so importing the package doesn't restyle a user's other notebook charts. Use Roboto, falling back to Helvetica, Arial and sans-serif. vl-convert sees only system fonts and directories registered with `vl_convert.register_font_directory`; check for Roboto at export time and note the fallback on stderr. Never fetch fonts over the network, which would break `--offline`. SVG keeps text as text, so it stays editable in Illustrator. Ship one neutral style in v0.1; newsroom house styles can live in a separate private package later.

### Output formats

| Extension | Output |
| --- | --- |
| `.html` (default) | Self-contained page saved with `inline=True`; Altair's default HTML loads Vega from a CDN and fails offline |
| `.svg` | Vector export for editing |
| `.png` | 2x scale raster |
| `.pdf` | Print and archive |
| `.vl.json` | Vega-Lite spec with inline data, for the Vega Editor or embedding with vega-embed |

Open a browser only with `--open`. Every chart file gets the same sidecar as data exports. Charts are exploratory; human review remains part of publication.

## Repeatable recipes

Add recipes after single-series fetch/export/chart is working. Use TOML, which Python can read through its standard library. Example proposed recipe:

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

Resolve relative paths against the recipe file. Keep fetching the latest available source separate from reproducing an earlier result: a recipe preserves settings, while its generated manifest records the exact input snapshot and software version. A future snapshot option can reproduce those saved inputs.

## Modules

Use `src/betteroff/` with `cli.py` for commands, `api.py` for orchestration, `catalog.py` and a packaged `catalog.toml` for identifiers, response order and polarity, a packaged `recessions.csv`, `fetch.py` for network access, `cache.py` for snapshots, `parsers/` for source layouts, `models.py` for contracts, `validate.py` for checks, `export.py` for outputs and `charts.py` for optional plotting. Add `recipes.py` when that feature lands.

Keep CLI functions thin. Parsing receives bytes and returns data plus metadata; it does not make network requests. Charting consumes the same validated Dataset returned to Python users.

## Delivery sequence and acceptance criteria

### 1. Prove table 34 end to end

Inspect actual files and access conditions. Implement one verified source route, parser and response mapping. Manually compare earliest, middle and latest available observations with the source. Confirm that the series represent the intended responses. Produce a clean DataFrame and CSV.

Done when source values and labels match, missingness is preserved and unexpected headers fail clearly.

### 2. Package a usable CLI

Add catalog search, describe, get, JSON/wide exports and the cache contract. Package the console entry point. Install locally with `uv tool install .` and exercise it outside the repository.

Done when a new user can find and export table 34 from help alone, piped data contains no progress text and `search` runs without importing pandas.

### 3. Add trend charts and four more tables

Add Altair outputs and trailing averages. Expand only after each table's format and meaning are verified. Add saved recipes once these commands are stable.

Done when HTML opens with networking disabled, static exports render correctly, missing months interrupt lines, colors match polarity across two different tables and rolling calculations have a hand-checked example.

### 4. Pilot and publish

Ask two journalists and one researcher to find a question, export it and repeat an update without assistance. Fix observed friction. Resolve data-use questions, finish the name clearance and publish installation instructions, an API reference and a short walkthrough. Support R users through documented CSV/JSON imports initially; assess a native R client only after demand is demonstrated.

Done when installation works on the supported platforms, the wheel contains the catalog, documentation distinguishes source lag from cache age and the intended distribution model is settled.

## Tests that matter

- Parser fixtures for representative headers, missing values and format changes; use synthetic public fixtures or permitted source fixtures.
- Source-to-output spot checks with expected values established independently of the parser.
- Tests for a login page returned with HTTP 200, truncated downloads and timeouts.
- Cache tests proving failed refreshes leave the last valid snapshot intact.
- Revision tests for changed and removed historical observations.
- CLI tests for stdout/stderr separation, exit codes, identifier aliases, format inference from extensions and format/extension conflicts.
- A subprocess test that `search` leaves pandas, HTTPX and Altair out of `sys.modules`.
- Rolling-average tests covering missing months and date filtering.
- Chart spec tests on `chart.to_dict()`: explicit nulls for missing months, the line mark's invalid mode, polarity colors, share-axis domain, footer text and recession bands. Skip pixel-snapshot comparisons, which break on font and renderer updates.
- One smoke render per static format and an installed-wheel smoke test.

Keep normal tests offline. A separate scheduled live check should fetch sparingly, validate privately and flag source changes without committing downloaded data to the repository. Pin the development environment with uv.lock; test reasonable dependency bounds before releasing.

## Explicitly deferred

No web service, data mirror, LLM query layer, respondent microdata, significance testing, arbitrary cross-survey comparisons, publication automation or full terminal dashboard in v0.1. Demographic series can follow once the all-household contract works. The first useful milestone is one command that retrieves table 34 correctly every time.

## Sources and implementation references

Checked October 12, 2026. These establish source availability, published access conditions and tool capabilities. Source download behavior still requires the phase-one investigation.

- [Michigan time-series interface](https://data.sca.isr.umich.edu/data-archive/mine.php)
- [Michigan tables](https://data.sca.isr.umich.edu/tables.php)
- [Michigan charts, including table 34](https://data.sca.isr.umich.edu/charts.php)
- [Michigan FAQ: detailed-data release lag](https://data.sca.isr.umich.edu/faq.php)
- [Michigan usage agreement](https://data.sca.isr.umich.edu/agreement.php)
- [uv tools and isolated installation](https://docs.astral.sh/uv/guides/tools/)
- [Typer help and command documentation](https://typer.tiangolo.com/tutorial/commands/help/)
- [HTTPX](https://www.python-httpx.org/)
- [Altair chart export, including offline HTML](https://altair-viz.github.io/user_guide/saving_charts.html)
- [vl-convert](https://github.com/vega/vl-convert)
- [Vega-Lite invalid-data modes](https://vega.github.io/vega-lite/docs/invalid-data.html)
- [Typer exceptions and pretty tracebacks](https://typer.tiangolo.com/tutorial/exceptions/)
- [NBER business cycle dates](https://www.nber.org/research/data/us-business-cycle-expansions-and-contractions)
- [Ruff](https://docs.astral.sh/ruff/)
- [Existing sentiment package on PyPI](https://pypi.org/project/sentiment/)
