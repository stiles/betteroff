# Charts

```bash
betteroff chart government_policy
betteroff chart 34 --rolling 12 --recessions -o gov.svg
betteroff chart 34 --measure index --start 2000 -o gov_index.png
betteroff chart 34 --theme brbg
betteroff chart 6 --rolling 12 --no-monthly --responses positive,negative
```

Charts are for checking and exploring the data. They make no editorial claims, and they still need a human edit before publication.

One function, `betteroff.charts.build_chart`, makes every chart. The CLI, `Dataset.chart()` and recipes all call it with the same validated data `get` returns. Calendar reindexing, rolling means and date trimming happen in pandas before the chart is built, so the chart plots data you can export and check.

## What you get

- One line per response, in catalog order. Colors follow polarity, so the favorable answer has the same color on every table, and so does the unfavorable one. Neutral answers are a mid gray; nonresponse is a thinner, dashed light gray. See [Color themes](#color-themes).
- Labels at each line's last value, nudged apart when they'd collide. Tables with more than four responses get a legend instead.
- One tooltip per month: hover anywhere to see every response's value that month. With `--rolling`, it shows both the average and the monthly value.
- Shares on a 0 to 100 axis, with a percent sign on the top label only. The index score uses 0 to 200 with a reference line at 100.
- A title from the catalog, a subtitle with the unit and any transformation, and a footer with the source, table number, latest month and retrieval date.

## Headline indexes

Charts of ICS, ICC and ICE fit the vertical axis to the values shown, in steps of 10, since the indexes have no fixed range. The subtitle gives the base period (1966 = 100) and the footer credits Michigan without a table number.

When the latest month is preliminary and in the displayed range, it's drawn as an open dot and the subtitle says so, for example "October 2026 is a preliminary reading; the open dot marks it." With `--rolling`, the dot sits on the last average, which includes the preliminary month. Tooltips give each month's release, preliminary or final.

## Missing months

The data is reindexed to every calendar month, with explicit nulls for months that have no reading. Lines use Vega-Lite's `break-paths-show-domains` mode, so they break at gaps instead of drawing a straight line across them. Readings with no reading in the month before or after are drawn as dots, since a line can't show them. When the displayed range has gaps, the subtitle says so.

By default, charts start when monthly data begins: January 1978 for most tables, July 2011 for tables 10 and 11 and September 1992 for table 45. Use `--start 1946` or any other month to show earlier readings.

Methodology breaks recorded in the catalog are drawn as a dashed line with a short label. Lines break there unless the catalog says the series is comparable across it. Tables 10 and 11 have one in 1972, when the question's horizon changed from four years to five.

## Rolling averages

`--rolling 12` is a trailing mean of 12 consecutive calendar months, and all 12 must have a reading. A window that includes a missing month produces no value, so a gap can't quietly become an 11-month average.

The mean is computed on the full history and then trimmed to the displayed range, so the first month shown has a proper average. Thin, light monthly lines stay behind the averages so smoothing doesn't hide volatility. To see only the averages, pass `--no-monthly`. Exports from `get` are never smoothed.

## Choosing responses

By default a chart draws every response. `--responses` draws only the ones you name, using response ids from `betteroff describe` or the polarity names `positive`, `negative`, `neutral` and `nonresponse`:

```bash
betteroff chart 6 --responses better_off,worse_off
betteroff chart 6 --responses positive,negative    # same lines, and works on any table
```

Polarity names are handy in recipes, where one `responses = ["positive", "negative"]` setting fits every question. A polarity the table doesn't have is skipped, but something has to match.

- Lines keep their usual colors, so "Better off" is the same blue whether or not "Same" is drawn.
- The subtitle lists the responses left out, since the lines shown no longer add up to 100.
- Tooltips list only the lines drawn. A table with more than four responses gets direct labels instead of a legend once four or fewer are shown.
- The sidecar records the response ids drawn.

Exports from `get` always include every response. `--responses` works with shares only, not `--measure index`.

## Recessions

`--recessions` shades NBER recessions from the peak month to the trough month, using a list packaged with Betteroff (`src/betteroff/data/recessions.csv`, checked against NBER on October 12, 2026). Bands are clipped to the displayed range. The footer credits NBER, and the sidecar records the list's source and check date. A test pins the list, so an update has to be deliberate.

## Color themes

Only the favorable and unfavorable responses get hue. Neutral answers ("same," "only fair," "uncertain") are a mid gray and nonresponse a light gray, so the two sides read first. Nonresponse lines are also thinner and dashed, and their labels use a darker gray so they stay readable. When two responses share a polarity, as with "don't know" and "no answer" in table 28, the second gets a lighter shade and a different dash.

Themes only change the two end colors. Run `betteroff themes` to see them with swatches:

| Theme | Favorable | Unfavorable | Notes |
| --- | --- | --- | --- |
| `okabe-ito` (default) | `#0072B2` blue | `#D55E00` vermillion | [Okabe and Ito](https://jfly.uni-koeln.de/color/)'s colorblind-safe palette; the two ends carry similar weight |
| `puor` | `#5e3c99` purple | `#e66101` orange | [ColorBrewer](https://colorbrewer2.org/) PuOr; the dark purple outweighs the orange |
| `brbg` | `#018571` teal | `#a6611a` brown | ColorBrewer BrBG; equally dark ends and no "red means bad" cue |
| `rdbu` | `#0571b0` blue | `#ca0020` red | ColorBrewer RdBu; the strongest good/bad cue, but can read as partisan, as on table 34 |
| `tol` | `#0077BB` blue | `#CC3311` red | [Paul Tol](https://personal.sron.nl/~pault/)'s vibrant scheme |

Every packaged theme comes from a published colorblind-safe palette, and a test checks that both end colors reach 3:1 contrast on white, the WCAG minimum for lines and other graphics. The sidecar records the theme's name and colors.

```bash
betteroff chart 34 --theme brbg
betteroff chart 34 --theme ./house.toml
```

In Python, `ds.chart(theme='brbg')`; in a recipe, `theme = 'brbg'`.

### Your own theme

A theme file sets the same keys as a packaged theme. Only `positive` and `negative` are required; anything left out uses the shared grays. Each color key is a list: the first shade, then one for a second response with the same polarity.

```toml
# house.toml
description = 'Our newsroom colors'
positive = ['#2a6f97', '#89c2d9']
negative = ['#bc4b51', '#f4a259']
# Optional overrides:
# neutral = ['#7a7a7a', '#a3a3a3']
# nonresponse = ['#bdbdbd', '#d6d6d6']
# nonresponse_label = '#8c8c8c'
# index = '#2b2b2b'   # line color for --measure index
```

The file name, without `.toml`, becomes the theme's name. In a recipe, a relative path resolves against the recipe's folder.

## Formats and size

| Extension | Output |
| --- | --- |
| `.html` | Self-contained page with Vega inlined; works with no network. Fills its container's width |
| `.svg` | Vector file with real text, editable in Illustrator |
| `.png` | Raster at 2x scale |
| `.pdf` | For print and archiving |
| `.vl.json` | Vega-Lite spec with inline data, for the [Vega Editor](https://vega.github.io/editor/) or vega-embed |

Static formats use a 960 by 540 frame (16:9). Change it with `--width` and `--height`. Rendering uses vl-convert, which needs no browser or Node.js.

## Fonts

Charts use [Inter](https://rsms.me/inter/), falling back to Helvetica, Arial and any sans-serif. Pick another family for one chart with `--font`, or set your own default with `BETTEROFF_FONT`:

```bash
betteroff chart 34 --font "IBM Plex Sans"
export BETTEROFF_FONT="Atkinson Hyperlegible Next"
```

In Python, `ds.chart(font='IBM Plex Sans')`; in a recipe, `font = 'IBM Plex Sans'`. An explicit font beats `BETTEROFF_FONT`, which beats Inter. Give one family name; Betteroff adds the fallbacks. The sidecar records the family.

Betteroff never downloads fonts, so a font has to be installed where the chart is drawn:

- HTML uses whatever the viewer's computer has. Inter isn't installed by default on macOS or Windows, so many readers see Helvetica or Arial.
- Static exports use fonts installed on your system. If Betteroff can't find the family among your font files, it says so on stderr and the export uses the fallback.

Direct labels at the right edge reserve room by character count, sized for wide faces such as Montserrat. A very wide or large font can still crowd the edge; widen the chart with `--width` if it does.

## Style

Styling is set on the chart's own marks and axes rather than through a global Altair theme, so importing Betteroff in a notebook doesn't restyle your other charts. Color themes change only line colors; the font is a separate setting, and sizes and gridlines are the same for every chart.
