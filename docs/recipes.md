# Recipes

A recipe is a TOML file listing the data files and charts you want. Running it again rebuilds the same outputs from the latest data, or from saved snapshots with `--offline`.

```bash
betteroff run betteroff.toml            # use the cache when it's fresh
betteroff run betteroff.toml --refresh  # check Michigan's site for every question
betteroff run betteroff.toml --offline  # rebuild from saved snapshots only
```

## Example

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

[[jobs]]
question = '34'
name = 'government_policy_index'
measure = 'index'
wide = true
data_formats = ['csv']
chart_formats = ['png']

[[jobs]]
question = 'home_buying_conditions'
wide = true
data_formats = ['csv']
```

## Settings

Top level:

| Key | Required | Meaning |
| --- | --- | --- |
| `schema_version` | yes | Must be `1` |
| `output_dir` | no | Where files go, relative to the recipe file. Default: the recipe's folder |

Each `[[jobs]]` table:

| Key | Default | Meaning |
| --- | --- | --- |
| `question` | required | Id or table number |
| `name` | question id | Base file name. Each job needs a unique name |
| `data_formats` | `[]` | Any of `csv`, `json` |
| `chart_formats` | `[]` | Any of `html`, `svg`, `png`, `pdf`, `vl.json` |
| `measure` | `share` | `share` or `index` |
| `wide` | `false` | Wide data files |
| `start`, `end` | full range | Months to include in data files and charts |
| `rolling` | none | Trailing average for charts |
| `raw` | `true` | Show monthly lines behind a rolling average |
| `recessions` | `false` | Shade NBER recessions |
| `width`, `height` | 960, 540 | Chart frame size |
| `theme` | `okabe-ito` | Color theme name, or a `.toml` theme file relative to the recipe |
| `font` | `BETTEROFF_FONT`, then Inter | Font family for chart text |

Each job needs at least one data or chart format. Unknown keys are errors, so a typo like `rollin = 12` fails instead of being ignored. The recipe is checked completely before anything is fetched or written.

A job with no `start` gets the full history in its data files, and its chart begins when monthly data does, as with `betteroff chart`.

## Outputs

Each job writes `NAME.FORMAT` and a `NAME.FORMAT.meta.json` sidecar in `output_dir`. Recipes overwrite the files they declare without `--force`; they never touch anything else.

Every run also writes `betteroff-run.json`:

```json
{
  "recipe": "betteroff.toml",
  "betteroff_version": "0.1.0",
  "run_at": "2026-10-12T22:00:00+00:00",
  "refresh": true,
  "offline": false,
  "jobs": [
    {
      "question": "government_policy",
      "name": "government_policy",
      "outputs": ["government_policy.csv", "government_policy.json", "government_policy.html", "government_policy.svg"],
      "snapshot": {"id": "1ec010d3b0d2", "sha256": "...", "retrieved_at": "...", "checked_at": "...", "mode": "fresh"},
      "latest_period": "2026-08"
    }
  ]
}
```

The recipe holds your settings. The run manifest records the exact input snapshot and software version behind each output. Each question is fetched once per run, even if several jobs use it.
