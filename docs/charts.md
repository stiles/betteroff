# Charts

```bash
betteroff chart government_policy
betteroff chart 34 --rolling 12 --recessions -o gov.svg
betteroff chart 34 --measure index --start 2000 -o gov_index.png
```

Charts are for checking and exploring the data. They make no editorial claims, and they still need a human edit before publication.

One function, `betteroff.charts.build_chart`, makes every chart. The CLI, `Dataset.chart()` and recipes all call it with the same validated data `get` returns. Calendar reindexing, rolling means and date trimming happen in pandas before the chart is built, so the chart plots data you can export and check.

## What you get

- One line per response, in catalog order. Colors follow polarity, so the favorable answer is the same blue and the unfavorable answer the same orange on every table. Neutral answers are purple and nonresponse gray. When two responses share a polarity, as with "don't know" and "no answer" in table 28, the second gets a lighter shade.
- Labels at each line's last value, nudged apart when they'd collide. Tables with more than four responses get a legend instead.
- One tooltip per month: hover anywhere to see every response's value that month. With `--rolling`, it shows both the average and the monthly value.
- Shares on a 0 to 100 axis, with a percent sign on the top label only. The index score uses 0 to 200 with a reference line at 100.
- A title from the catalog, a subtitle with the unit and any transformation, and a footer with the source, table number, latest month and retrieval date.

## Missing months

The data is reindexed to every calendar month, with explicit nulls for months that have no reading. Lines use Vega-Lite's `break-paths-show-domains` mode, so they break at gaps instead of drawing a straight line across them. Readings with no reading in the month before or after are drawn as dots, since a line can't show them. When the displayed range has gaps, the subtitle says so.

By default, charts start when monthly data begins: January 1978 for most tables, July 2011 for tables 10 and 11 and September 1992 for table 45. Use `--start 1946` or any other month to show earlier readings.

Methodology breaks recorded in the catalog are drawn as a dashed line with a short label. Lines break there unless the catalog says the series is comparable across it. Tables 10 and 11 have one in 1972, when the question's horizon changed from four years to five.

## Rolling averages

`--rolling 12` is a trailing mean of 12 consecutive calendar months, and all 12 must have a reading. A window that includes a missing month produces no value, so a gap can't quietly become an 11-month average.

The mean is computed on the full history and then trimmed to the displayed range, so the first month shown has a proper average. Thin, light monthly lines stay behind the averages so smoothing doesn't hide volatility; `--no-raw` hides them. Exports from `get` are never smoothed.

## Recessions

`--recessions` shades NBER recessions from the peak month to the trough month, using a list packaged with Betteroff (`src/betteroff/data/recessions.csv`, checked against NBER on October 12, 2026). Bands are clipped to the displayed range. The footer credits NBER, and the sidecar records the list's source and check date. A test pins the list, so an update has to be deliberate.

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

Charts ask for Roboto, then Helvetica, Arial and any sans-serif. HTML uses whatever the viewer's browser has. Static exports can only use fonts installed on your system; if Roboto isn't installed, Betteroff says so on stderr and the export uses the fallback. Betteroff never downloads fonts.

## Style

There's one neutral style. It's set on the chart's own marks and axes rather than through a global Altair theme, so importing Betteroff in a notebook doesn't restyle your other charts.
