# Python API

```python
import betteroff as bo
```

`import betteroff` is cheap: pandas, HTTPX and Altair load only when you call something that needs them.

## Finding questions

```python
bo.search('home values')        # list[Question], best match first
bo.list_questions()             # every supported question
q = bo.describe('34')           # Question for an id or table number
q.wording, q.responses, q.notes
```

`Question` is a frozen dataclass with `id`, `table`, `title`, `wording`, `responses`, `keywords`, `notes`, `breaks` and `monthly_since`. Each `Response` has `id`, `label`, `source_label` and `polarity` (`positive`, `neutral`, `negative` or `nonresponse`). `q.to_dict()` gives a JSON-ready copy.

## Getting data

```python
ds = bo.get(
    'government_policy',   # id or table number
    refresh=False,         # True forces a source check
    offline=False,         # True uses the saved snapshot only
    start=None,            # 'YYYY', 'YYYY-MM', 'YYYY-MM-DD' or datetime.date
    end=None,
    measure='share',       # or 'index'
)
```

`get` follows the same cache rules as the CLI: a snapshot checked in the past 24 hours is reused; otherwise the source is checked. If an automatic check fails, you get the saved snapshot and a `BetteroffWarning`. If `refresh=True` fails, `get` raises.

## The Dataset

| Attribute | Contents |
| --- | --- |
| `ds.data` | Tidy DataFrame: `date`, `question_id`, `measure`, `response_id`, `response_label`, `value`, `unit`, `cases`, `population` |
| `ds.wide()` | One row per month: `date`, one column per response id in catalog order, `cases` |
| `ds.metadata` | Dict with question, source, snapshot, coverage, notes, quality flags and revisions |
| `ds.question` | The `Question` |
| `ds.frame` | Full history in source shape, including `total` and `index`, ignoring `start`, `end` and `measure` |
| `ds.latest_period` | Newest survey month, such as `'2026-08'` |

`date` is the first day of the survey month. `value` is a float in the source's precision; missing values stay `NaN` and are never filled with zero. `cases` is the number of interviews.

`Dataset` is a plain dataclass, not a DataFrame subclass. Make a new view with `dataclasses.replace(ds, measure='index', start=date(2000, 1, 1))`.

## Charts

```python
chart = ds.chart(
    rolling=12,         # trailing mean over 12 calendar months
    monthly=True,       # thin monthly lines behind the average; raw= is the old name
    responses=None,     # e.g. ['positive', 'negative'] or 'better_off,worse_off'
    recessions=True,    # NBER bands
    start='2000',       # displayed range; rolling is computed on full history first
    end=None,
    width=None,         # frame size in px, default 960 x 540
    height=None,
    container=False,    # True: fill the HTML container's width
    theme='okabe-ito',  # or 'puor', 'brbg', 'rdbu', 'tol', a .toml path, or a Theme
    font=None,          # one font family; defaults to $BETTEROFF_FONT, then 'Inter'
)
chart                   # displays inline in Jupyter
chart.save('gov.html', inline=True)   # offline HTML
chart.save('gov.svg')
chart.to_dict()         # the Vega-Lite spec
```

`chart` is an ordinary `altair.LayerChart`. Styling is set on its marks and axes, not through a global theme, so it doesn't change your other charts, and you can layer on it:

```python
import altair as alt
import pandas as pd

rule = alt.Chart(pd.DataFrame({'date': ['2020-03-01']})).mark_rule().encode(x='date:T')
chart + rule
```

To use the CLI's export rules, including the installed-font check and 2x PNG:

```python
from pathlib import Path
from betteroff.charts import save_chart

save_chart(chart, Path('gov.png'), 'png')
```

Charts need the extra: `uv add 'betteroff[charts]'`. Without it, `ds.chart()` raises `MissingDependencyError` with the install command.

## Warnings and logging

Conditions that change what the data means are issued as `betteroff.BetteroffWarning`:

- An offline snapshot was used.
- An automatic source check failed and a stale snapshot was used.
- The source revised or removed months since the previous snapshot.
- The question wording in the source no longer matches the catalog.

Routine notices, such as "Checking source" or "no new months," go to the `betteroff` logger at INFO level. Python hides them by default; turn them on with `logging.basicConfig(level=logging.INFO)`.

## Errors

All errors subclass `betteroff.errors.BetteroffError`, with `message`, an `action` suggesting a fix and an `exit_code` that the CLI uses.

| Class | Exit code | When |
| --- | --- | --- |
| `InputError` | 2 | Unknown id, bad date or measure, bad recipe, existing output |
| `MissingDependencyError` | 2 | Charts requested without the `charts` extra |
| `FetchError` | 3 | Network failure, access page, truncated download, no offline snapshot |
| `ValidationError` | 4 | The source file no longer matches the catalog or parser |
