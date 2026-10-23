"""Exploratory Altair charts built from a validated Dataset.

Data work (calendar reindexing, rolling means, trimming) happens in pandas so the
chart plots exactly what users can export. Styling is set on marks and axes, not a
global theme, so importing betteroff never restyles a user's other charts.
"""

from __future__ import annotations

import csv
import logging
import math
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from .catalog import Question, load_catalog
from .errors import InputError, MissingDependencyError
from .themes import Theme, load_theme

if TYPE_CHECKING:
    import altair as alt

    from .models import Dataset

log = logging.getLogger('betteroff')

DEFAULT_FONT = 'Inter'
FALLBACK_FONTS = 'Helvetica, Arial, sans-serif'
FONT_ENV = 'BETTEROFF_FONT'
FONT_FILE_SUFFIXES = {'.ttf', '.otf', '.ttc', '.otc'}
TEXT_COLOR = '#222222'
MUTED = '#666666'
GRID = '#e2e2e2'
RECESSION_FILL = '#ececec'
NONRESPONSE_DASHES = [[4, 3], [2, 2]]
NONRESPONSE_WIDTH = 1.5
LINE_WIDTH = 2.25
STATIC_WIDTH, STATIC_HEIGHT = 960, 540
MAX_DIRECT_LABELS = 4
LABEL_CHAR_WIDTH = 7.2  # Px per character of a 12px bold label; fits wide faces like Montserrat
LINE_INVALID_MODE = 'break-paths-show-domains'
RECESSIONS_SOURCE = 'NBER Business Cycle Dating Committee'
RECESSIONS_URL = 'https://www.nber.org/research/data/us-business-cycle-expansions-and-contractions'
RECESSIONS_CHECKED = '2026-10-12'
CHART_FORMATS = ('html', 'svg', 'png', 'pdf', 'vl.json')
POLARITIES = ('positive', 'neutral', 'negative', 'nonresponse')


def require_altair() -> Any:
    try:
        import altair
    except ImportError:
        raise MissingDependencyError(
            'Charts need the optional chart dependencies (Altair and vl-convert).',
            "Install with `uv tool install 'betteroff[charts]'` or `uv add 'betteroff[charts]'`.",
        ) from None
    return altair


@cache
def recession_dates() -> tuple[tuple[date, date], ...]:
    text = resources.files('betteroff').joinpath('data/recessions.csv').read_text('utf-8')
    rows = csv.DictReader(text.splitlines())
    return tuple((date.fromisoformat(r['peak']), date.fromisoformat(r['trough'])) for r in rows)


def _shades(question: Question, colors: dict[str, tuple[str, ...]]) -> dict[str, str]:
    used: dict[str, int] = {}
    out = {}
    for r in question.responses:
        shades = colors[r.polarity]
        out[r.id] = shades[min(used.get(r.polarity, 0), len(shades) - 1)]
        used[r.polarity] = used.get(r.polarity, 0) + 1
    return out


def response_colors(question: Question, theme: str | Path | Theme | None = None) -> dict[str, str]:
    return _shades(question, load_theme(theme).colors)


def _line_styles(question: Question) -> tuple[dict[str, list[int]], dict[str, float]]:
    dashes: dict[str, list[int]] = {}
    widths: dict[str, float] = {}
    n = 0
    for r in question.responses:
        if r.polarity == 'nonresponse':
            dashes[r.id] = NONRESPONSE_DASHES[min(n, len(NONRESPONSE_DASHES) - 1)]
            widths[r.id] = NONRESPONSE_WIDTH
            n += 1
        else:
            dashes[r.id] = [1, 0]
            widths[r.id] = LINE_WIDTH
    return dashes, widths


def select_responses(
    question: Question, responses: str | Sequence[str] | None, measure: str = 'share'
) -> list[str] | None:
    """Response ids to draw, in catalog order, from ids and polarity names.

    A string is split on commas. None means every response.
    """
    if responses is None:
        return None
    if question.is_index:
        raise InputError(
            f'{question.title} is a single index; it has no responses to choose.',
            'Drop the response selection.',
        )
    if measure == 'index':
        raise InputError(
            'Responses can only be chosen for shares, not the index score.',
            'Remove the response selection, or chart shares instead.',
        )
    if measure in ('median', 'mean'):
        raise InputError(
            f'Responses can only be chosen for shares, not {measure}.',
            'Remove the response selection, or chart shares instead.',
        )
    items = responses.split(',') if isinstance(responses, str) else list(responses)
    wanted = [str(i).strip() for i in items if str(i).strip()]
    if question.is_inflation and measure == 'summary':
        summary_cols = ['median', 'mean', 'p25', 'p75', 'rng']
        chosen = [c for c in summary_cols if c in wanted]
        if not chosen:
            raise InputError(
                'No valid summary metrics given.',
                f'Use one or more of: {", ".join(summary_cols)}.',
            )
        return chosen
    ids = [r.id for r in question.responses]
    valid = ', '.join(
        [*ids, *(p for p in POLARITIES if any(r.polarity == p for r in question.responses))]
    )
    if not wanted:
        raise InputError('No responses given.', f'Use one or more of: {valid}.')
    unknown = [w for w in wanted if w not in ids and w not in POLARITIES]
    if unknown:
        raise InputError(
            f'Table {question.table} has no response {", ".join(repr(u) for u in unknown)}.',
            f'Use one or more of: {valid}.',
        )
    chosen = [r.id for r in question.responses if r.id in wanted or r.polarity in wanted]
    if not chosen:
        raise InputError(
            f'Table {question.table} has no {" or ".join(wanted)} responses.',
            f'Use one or more of: {valid}.',
        )
    return chosen


def monthly(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Reindex to every calendar month so gaps are explicit nulls."""
    idx = pd.date_range(frame['date'].min(), frame['date'].max(), freq='MS', name='date')
    return frame.set_index('date')[columns].reindex(idx).reset_index()


def trailing_mean(wide: pd.DataFrame, columns: list[str], window: int) -> pd.DataFrame:
    """Trailing mean of `window` consecutive calendar months, requiring all of them."""
    out = wide.copy()
    out[columns] = wide[columns].rolling(window, min_periods=window).mean()
    return out


@dataclass
class Prepared:
    main: pd.DataFrame  # values to draw as lines (smoothed when rolling)
    raw: pd.DataFrame | None  # monthly values behind a rolling average
    columns: list[str]
    start: pd.Timestamp
    end: pd.Timestamp


def prepare(
    dataset: Dataset,
    rolling: int | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
) -> Prepared:
    """Reindex, smooth over full history, then trim to the displayed range."""
    from .models import parse_date

    if rolling is not None and rolling < 2:
        raise InputError('--rolling must be at least 2 months.', 'Try --rolling 3 or --rolling 12.')
    columns = dataset.value_columns
    full = monthly(dataset.frame, columns)
    main = trailing_mean(full, columns, rolling) if rolling else full

    first, last = full['date'].min(), full['date'].max()
    start_d = parse_date(start, 'start') or dataset.start
    end_d = parse_date(end, 'end') or dataset.end
    if start_d is None:
        monthly_since = dataset.question.monthly_since or load_catalog().monthly_since
        start_d = max(first.date(), monthly_since)
    lo = max(pd.Timestamp(start_d), first)
    hi = min(pd.Timestamp(end_d), last) if end_d else last
    if lo > hi:
        raise InputError(
            f'No data between {lo:%Y-%m} and {hi:%Y-%m}.',
            f'This series covers {first:%Y-%m} to {last:%Y-%m}.',
        )

    def trim(f: pd.DataFrame) -> pd.DataFrame:
        return f[(f['date'] >= lo) & (f['date'] <= hi)].reset_index(drop=True)

    return Prepared(
        main=trim(main),
        raw=trim(full) if rolling else None,
        columns=columns,
        start=lo,
        end=hi,
    )


def _segments(dates: pd.Series, question: Question) -> pd.Series:
    seg = pd.Series(0, index=dates.index)
    for b in question.breaks:
        if not b.comparable:
            seg += (dates >= pd.Timestamp(b.date)).astype(int)
    return seg


def _long(
    wide: pd.DataFrame, columns: list[str], labels: dict[str, str], q: Question
) -> pd.DataFrame:
    w = wide.assign(segment=_segments(wide['date'], q))
    long = w.melt(id_vars=['date', 'segment'], value_vars=columns, var_name='response_id')
    long['label'] = long['response_id'].map(labels)
    return long


def _isolated(wide: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Observations with no neighbor in either adjacent month; lines can't show them."""
    mask = pd.DataFrame(
        {c: wide[c].notna() & wide[c].shift(1).isna() & wide[c].shift(-1).isna() for c in columns}
    )
    return wide[columns].where(mask).assign(date=wide['date'])


def _dodge(values: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """Spread label positions at least `gap` apart while keeping their order."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    pos = [values[i] for i in order]
    for i in range(1, len(pos)):
        pos[i] = max(pos[i], pos[i - 1] + gap)
    if pos and pos[-1] > hi:
        pos[-1] = hi
        for i in range(len(pos) - 2, -1, -1):
            pos[i] = min(pos[i], pos[i + 1] - gap)
    if pos and pos[0] < lo:
        pos[0] = lo
        for i in range(1, len(pos)):
            pos[i] = max(pos[i], pos[i - 1] + gap)
    out = [0.0] * len(values)
    for k, i in enumerate(order):
        out[i] = pos[k]
    return out


def _preliminary_month(dataset: Dataset, prep: Prepared) -> pd.Timestamp | None:
    """The preliminary month of a headline index, if it falls in the displayed range."""
    frame = dataset.frame
    if 'preliminary' not in frame or not frame['preliminary'].any():
        return None
    when = pd.Timestamp(frame.loc[frame['preliminary'].astype(bool), 'date'].iloc[-1])
    return when if prep.start <= when <= prep.end else None


def _month(ts: pd.Timestamp | date) -> str:
    return f'{ts:%B %Y}'


def _day(iso: str) -> str:
    d = pd.Timestamp(iso)
    return f'{d:%b} {d.day}, {d.year}'


def build_chart(
    dataset: Dataset,
    *,
    rolling: int | None = None,
    monthly: bool = True,
    responses: str | Sequence[str] | None = None,
    recessions: bool = False,
    start: str | date | None = None,
    end: str | date | None = None,
    width: int | None = None,
    height: int | None = None,
    container: bool = False,
    theme: str | Path | Theme | None = None,
    font: str | None = None,
    raw: bool | None = None,
) -> alt.LayerChart:
    """Build the standard exploratory chart.

    `width` and `height` set the whole frame (default 960x540, 16:9); `container`
    makes the chart fill its HTML container's width instead. `theme` is a packaged
    theme name, a path to a theme TOML file or a `Theme`. `font` is one font family
    name; it defaults to $BETTEROFF_FONT, then Inter, and falls back to Helvetica,
    Arial and sans-serif.

    `monthly` draws thin monthly lines behind a rolling average; it has no effect
    without `rolling`. `responses` limits the lines to response ids or polarity
    names ("positive", "negative", "neutral", "nonresponse"), as a list or a
    comma-separated string. `raw` is the old name for `monthly`.
    """
    alt = require_altair()
    catalog = load_catalog()
    q = dataset.question
    th = load_theme(theme)
    family = resolve_font(font)
    font_css = font_stack(family)
    if raw is not None:
        monthly = raw
    selected = select_responses(q, responses, dataset.measure)
    prep = prepare(dataset, rolling, start, end)
    is_index = dataset.measure == 'index'
    is_stat = q.is_inflation and dataset.measure in ('median', 'mean', 'summary')
    columns = selected or prep.columns

    ticks: list[int] | None
    if is_index:
        labels = {'index': q.label if q.is_index else catalog.index_label}
        colors = {'index': th.index}
        label_colors = colors
        dashes: dict[str, list[int]] = {'index': [1, 0]}
        widths: dict[str, float] = {'index': LINE_WIDTH}
        domain, ticks = [0, 200], [0, 50, 100, 150, 200]
        if q.is_index:
            # Headline indexes have no fixed range; fit the axis to the values shown.
            drawn = prep.raw if prep.raw is not None and monthly else prep.main
            values = drawn['index'].dropna()
            domain = [
                int(math.floor(values.min() / 10) * 10),
                int(math.ceil(values.max() / 10) * 10),
            ]
            ticks = None
        unit_suffix = ''
    elif is_stat:
        stat_labels = {
            'median': 'Median',
            'mean': 'Mean',
            'p25': '25th percentile',
            'p75': '75th percentile',
            'rng': 'Interquartile range',
        }
        labels = {c: stat_labels.get(c, c.title()) for c in columns}
        stat_colors = {
            'median': th.index,
            'mean': th.colors['positive'][0] if len(columns) > 1 else th.index,
            'p25': '#7a7a7a',
            'p75': '#7a7a7a',
            'rng': '#a0a0a0',
        }
        stat_dashes: dict[str, list[int]] = {
            'median': [1, 0],
            'mean': [4, 3] if len(columns) > 1 else [1, 0],
            'p25': [2, 2],
            'p75': [2, 2],
            'rng': [1, 2],
        }
        stat_widths: dict[str, float] = {
            'median': LINE_WIDTH,
            'mean': LINE_WIDTH,
            'p25': 1.5,
            'p75': 1.5,
            'rng': 1.25,
        }
        colors = {c: stat_colors.get(c, th.index) for c in columns}
        label_colors = colors
        dashes = {c: stat_dashes.get(c, [1, 0]) for c in columns}
        widths = {c: stat_widths.get(c, LINE_WIDTH) for c in columns}
        drawn = prep.raw if prep.raw is not None and monthly else prep.main
        vals = drawn[columns].dropna(how='all')
        if not vals.empty:
            v_min = float(vals.min().min())
            v_max = float(vals.max().max())
            lo = min(0.0, float(math.floor(v_min)))
            hi = max(6.0, float(math.ceil(v_max) + 1.0))
            domain = [lo, hi]
        else:
            domain = [0.0, 10.0]
        ticks = None
        unit_suffix = ' (%)'
    else:
        labels = {r.id: r.label for r in q.responses}
        colors = _shades(q, th.colors)
        label_colors = _shades(q, {**th.colors, 'nonresponse': (th.nonresponse_label,)})
        dashes, widths = _line_styles(q)
        domain, ticks = [0, 100], [0, 25, 50, 75, 100]
        unit_suffix = ' (%)'

    direct_labels = len(columns) <= MAX_DIRECT_LABELS and not is_index
    label_space = (
        max(len(labels[c]) for c in columns) * LABEL_CHAR_WIDTH + 14 if direct_labels else 10
    )
    total_w = width or STATIC_WIDTH
    total_h = height or STATIC_HEIGHT
    plot_w: Any = 'container' if container else max(int(total_w - 45 - label_space), 200)
    plot_h = max(int(total_h - 150 - (30 if not direct_labels and not is_index else 0)), 120)

    x_domain = [
        alt.DateTime(year=prep.start.year, month=prep.start.month, date=1),
        alt.DateTime(year=prep.end.year, month=prep.end.month, date=1),
    ]
    span_years = (prep.end - prep.start).days / 365.25
    x = alt.X(
        'date:T',
        title=None,
        scale=alt.Scale(domain=x_domain),
        axis=alt.Axis(
            format='%Y' if span_years >= 3 else '%b %Y',
            tickCount=max(int(plot_w / 90), 3) if isinstance(plot_w, int) else 8,
            grid=False,
            labelFont=font_css,
            labelColor=MUTED,
            labelFontSize=11,
            tickColor=GRID,
            domainColor='#bbbbbb',
            labelOverlap=True,
        ),
    )
    if is_index:
        label_expr = alt.Undefined
    elif is_stat:
        label_expr = "datum.label + '%'"
    else:
        label_expr = "datum.value == 100 ? datum.label + '%' : datum.label"
    y = alt.Y(
        'value:Q',
        title=None,
        scale=alt.Scale(domain=domain, nice=False, zero=False),
        axis=alt.Axis(
            values=ticks if ticks is not None else alt.Undefined,
            labelExpr=label_expr,
            grid=True,
            gridColor=GRID,
            domain=False,
            ticks=False,
            labelFont=font_css,
            labelColor=MUTED,
            labelFontSize=11,
            labelPadding=6,
        ),
    )
    color_domain = [labels[c] for c in columns]
    color = alt.Color(
        'label:N',
        scale=alt.Scale(domain=color_domain, range=[colors[c] for c in columns]),
        legend=None
        if direct_labels or is_index
        else alt.Legend(
            orient='top',
            title=None,
            direction='horizontal',
            labelFont=font_css,
            labelColor=TEXT_COLOR,
            symbolType='stroke',
            symbolStrokeWidth=3,
        ),
    )
    dash = alt.StrokeDash(
        'label:N',
        scale=alt.Scale(domain=color_domain, range=[dashes[c] for c in columns]),
        # Same field as color, so Vega-Lite merges them into one legend
        legend=None if direct_labels or is_index else alt.Legend(orient='top', title=None),
    )
    # A one-value scale range falls back to Vega-Lite's default width, so one line gets a value.
    stroke_width: Any = (
        alt.value(widths[columns[0]])
        if len(columns) == 1
        else alt.StrokeWidth(
            'label:N',
            scale=alt.Scale(domain=color_domain, range=[widths[c] for c in columns]),
            legend=None,
        )
    )
    label_color = alt.Color(
        'label:N',
        scale=alt.Scale(domain=color_domain, range=[label_colors[c] for c in columns]),
        legend=None,
    )

    layers: list[Any] = []

    if recessions:
        bands = [
            (max(pd.Timestamp(p), prep.start), min(pd.Timestamp(t), prep.end))
            for p, t in recession_dates()
            if pd.Timestamp(t) >= prep.start and pd.Timestamp(p) <= prep.end
        ]
        if bands:
            rec = pd.DataFrame(bands, columns=['date', 'end'])
            layers.append(
                alt.Chart(rec)
                .mark_rect(color=RECESSION_FILL, minBandSize=2)
                .encode(x=x, x2='end:T')
            )

    if is_index and not q.is_index:
        layers.append(
            alt.Chart(pd.DataFrame({'value': [100]}))
            .mark_rule(color='#9a9a9a', strokeWidth=1)
            .encode(y=y)
        )

    if is_stat and domain[0] < 0:
        layers.append(
            alt.Chart(pd.DataFrame({'value': [0]}))
            .mark_rule(color='#9a9a9a', strokeWidth=1)
            .encode(y=y)
        )

    visible_breaks = [b for b in q.breaks if prep.start < pd.Timestamp(b.date) <= prep.end]
    if visible_breaks:
        brk = pd.DataFrame(
            {
                'date': [pd.Timestamp(b.date) for b in visible_breaks],
                'text': [b.label for b in visible_breaks],
            }
        )
        layers.append(
            alt.Chart(brk).mark_rule(color=MUTED, strokeDash=[4, 3], strokeWidth=1).encode(x=x)
        )
        layers.append(
            alt.Chart(brk)
            .mark_text(align='left', baseline='top', dx=4, font=font_css, fontSize=10, color=MUTED)
            .encode(x=x, y=alt.value(2), text='text:N')
        )

    main_long = _long(prep.main, columns, labels, q)
    if prep.raw is not None and monthly:
        raw_long = _long(prep.raw, columns, labels, q)
        layers.append(
            alt.Chart(raw_long)
            .mark_line(strokeWidth=1, opacity=0.35, invalid=LINE_INVALID_MODE)
            .encode(x=x, y=y, color=color, strokeDash=dash, detail='segment:N')
        )
    layers.append(
        alt.Chart(main_long)
        .mark_line(invalid=LINE_INVALID_MODE)
        .encode(
            x=x, y=y, color=color, strokeDash=dash, strokeWidth=stroke_width, detail='segment:N'
        )
    )

    iso = _long(_isolated(prep.main, columns), columns, labels, q).dropna(subset=['value'])
    if not iso.empty:
        layers.append(
            alt.Chart(iso)
            .mark_point(filled=True, size=16, opacity=0.9)
            .encode(x=x, y=y, color=color)
        )

    prelim = _preliminary_month(dataset, prep)
    if prelim is not None:
        last = prep.main.loc[prep.main['date'] == prelim, 'index']
        if not last.isna().all():
            layers.append(
                alt.Chart(pd.DataFrame({'date': [prelim], 'value': [float(last.iloc[0])]}))
                .mark_point(
                    filled=True, fill='white', stroke=th.index, strokeWidth=2, size=60, opacity=1
                )
                .encode(x=x, y=y)
            )

    # One tooltip per month: an invisible rule carrying every response's value.
    tip = prep.main[['date', *columns]].copy()
    tooltip = [alt.Tooltip('date:T', title='Month', format='%B %Y')]
    fmt = '.1f' if (rolling or is_stat) else '.0f'
    for c in columns:
        title = f'{labels[c]}{unit_suffix}'
        if rolling:
            title = f'{labels[c]}, {rolling}-mo. avg.{unit_suffix}'
        tooltip.append(alt.Tooltip(f'{c}:Q', title=title, format=fmt))
    if prep.raw is not None:
        for c in columns:
            tip[f'{c}__monthly'] = prep.raw[c].to_numpy()
            tooltip.append(
                alt.Tooltip(
                    f'{c}__monthly:Q',
                    title=f'{labels[c]}, monthly{unit_suffix}',
                    format='.1f' if is_stat else '.0f',
                )
            )
    if q.is_index:
        status = dataset.frame.set_index('date')['preliminary'].astype(bool)
        tip['release'] = tip['date'].map(status).map({True: 'Preliminary', False: 'Final'})
        tooltip.append(alt.Tooltip('release:N', title='Release'))
    nearest = alt.selection_point(
        name='hover',
        nearest=True,
        on='pointerover',
        clear='pointerout',
        fields=['date'],
        empty=False,
    )
    when_near = alt.when(nearest)
    layers.append(
        alt.Chart(main_long)
        .mark_point(filled=True, size=40)
        .encode(x=x, y=y, color=color)
        .transform_filter(nearest)
    )
    layers.append(
        alt.Chart(tip)
        .mark_rule(color='#888888', strokeWidth=1)
        .encode(
            x=x,
            opacity=when_near.then(alt.value(0.6)).otherwise(alt.value(0)),
            tooltip=tooltip,
        )
        .add_params(nearest)
    )

    if direct_labels:
        ends = []
        for c in columns:
            s = prep.main[['date', c]].dropna()
            if not s.empty:
                ends.append(
                    {'date': s['date'].iloc[-1], 'value': float(s[c].iloc[-1]), 'label': labels[c]}
                )
        if ends:
            gap = (domain[1] - domain[0]) * 13 / plot_h
            placed = _dodge([e['value'] for e in ends], gap, domain[0], domain[1])
            for e, p in zip(ends, placed, strict=True):
                e['latest'], e['value'] = e['value'], p
            layers.append(
                alt.Chart(pd.DataFrame(ends))
                .mark_text(
                    align='left',
                    baseline='middle',
                    dx=6,
                    font=font_css,
                    fontSize=12,
                    fontWeight='bold',
                )
                .encode(x=x, y=y, text='label:N', color=label_color)
            )

    meta = dataset.metadata
    footer = [
        f'Source: {catalog.attribution}'
        + ('.' if q.is_index else f', table {q.table}.')
        + (' Recession dates: NBER.' if recessions else ''),
        f'Latest month: {_month(pd.Timestamp(meta["coverage"]["latest_period"] + "-01"))}. '
        f'Retrieved {_day(meta["snapshot"]["retrieved_at"])}.',
    ]
    layers.append(
        alt.Chart(pd.DataFrame({'text': ['\n'.join(footer)]}))
        .mark_text(
            align='left',
            baseline='top',
            font=font_css,
            fontSize=10,
            color=MUTED,
            lineBreak='\n',
            lineHeight=14,
        )
        .encode(x=alt.value(0), y=alt.value(plot_h + 30), text='text:N')
    )

    if q.is_index:
        subtitle = [f'Index, {catalog.headline.base}']
    elif is_index:
        subtitle = [f'{catalog.index_label}: percent favorable minus percent unfavorable, plus 100']
    elif q.is_inflation:
        if dataset.measure == 'median':
            subtitle = ['Median expected price change per year, percent']
        elif dataset.measure == 'mean':
            subtitle = ['Mean expected price change per year, percent']
        elif dataset.measure == 'summary':
            subtitle = ['Expected price change per year, percent']
        else:
            subtitle = ['Percent of respondents']
    else:
        subtitle = ['Percent of respondents']
    if rolling:
        subtitle[0] += f', {rolling}-month trailing average'
        if monthly:
            subtitle[0] += '; thin lines show monthly values'
    if prelim is not None:
        subtitle.append(f'{_month(prelim)} is a preliminary reading; the open dot marks it')
    if selected and len(selected) < len(prep.columns):
        hidden = [labels[c] for c in prep.columns if c not in selected]
        subtitle.append(f'Not shown: {"; ".join(hidden)}')
    shown = prep.raw if prep.raw is not None else prep.main
    if shown[columns].isna().all(axis=1).any():
        subtitle.append(
            'Gaps are months without a reading'
            + ('; dots mark readings with no adjacent month' if not iso.empty else '')
        )

    chart = alt.layer(*layers).properties(
        width=plot_w,
        height=plot_h,
        title=alt.TitleParams(
            text=q.title,
            subtitle=subtitle,
            anchor='start',
            frame='group',
            font=font_css,
            fontSize=18,
            fontWeight='bold',
            color=TEXT_COLOR,
            subtitleFont=font_css,
            subtitleFontSize=13,
            subtitleColor=MUTED,
            offset=14,
        ),
        view=alt.ViewBackground(stroke=None),
        usermeta={'betteroff': {'font': family}},
    )
    return chart


def resolve_font(font: str | None = None) -> str:
    """The font family to use: `font`, then $BETTEROFF_FONT, then Inter."""
    from_env = font is None
    family = (os.environ.get(FONT_ENV) or DEFAULT_FONT) if from_env else font
    family = (family or '').strip()
    if not family or re.search(r'[,;"\'{}]', family):
        where = f'{FONT_ENV} ' if from_env else ''
        raise InputError(
            f'Font {where}"{family}" is not a single font family name.',
            'Pass one family, such as "IBM Plex Sans"; Betteroff adds the fallbacks.',
        )
    return family


def font_stack(family: str) -> str:
    return f'{family}, {FALLBACK_FONTS}'


def font_dirs() -> list[Path]:
    home = Path.home()
    dirs = [
        home / 'Library/Fonts',
        Path('/Library/Fonts'),
        Path('/System/Library/Fonts'),
        Path('/usr/share/fonts'),
        Path('/usr/local/share/fonts'),
        home / '.local/share/fonts',
        home / '.fonts',
    ]
    if sys.platform == 'win32':
        windir = Path(os.environ.get('WINDIR', 'C:/Windows'))
        dirs += [windir / 'Fonts', home / 'AppData/Local/Microsoft/Windows/Fonts']
    return [d for d in dirs if d.is_dir()]


def _squash(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())


@cache
def _font_file_names() -> tuple[str, ...]:
    return tuple(
        _squash(f.stem)
        for d in font_dirs()
        for f in d.rglob('*')
        if f.suffix.lower() in FONT_FILE_SUFFIXES
    )


def font_installed(family: str) -> bool:
    """Best guess from file names, which nearly always start with the family name."""
    key = _squash(family)
    return any(name.startswith(key) for name in _font_file_names())


def chart_font(chart: alt.LayerChart) -> str:
    meta = getattr(chart, 'usermeta', None)
    if isinstance(meta, dict):
        family = meta.get('betteroff', {}).get('font')
        if isinstance(family, str):
            return family
    return resolve_font()


def chart_format(path: Path) -> str | None:
    name = path.name.lower()
    if name.endswith('.vl.json'):
        return 'vl.json'
    suffix = path.suffix.lower().lstrip('.')
    return suffix if suffix in CHART_FORMATS else None


def save_chart(chart: alt.LayerChart, path: Path, fmt: str) -> None:
    require_altair()
    if fmt in ('svg', 'png', 'pdf') and not font_installed(family := chart_font(chart)):
        log.info(
            '%s not found; static export uses Helvetica, Arial or another sans-serif font.',
            family,
        )
    if fmt == 'html':
        chart.save(str(path), format='html', inline=True)
    elif fmt == 'vl.json':
        path.write_text(chart.to_json(indent=2), encoding='utf-8')
    elif fmt == 'png':
        chart.save(str(path), format='png', scale_factor=2)
    elif fmt == 'svg':
        chart.save(str(path), format='svg')
    elif fmt == 'pdf':
        chart.save(str(path), format='pdf')
    else:
        raise InputError(
            f'Unknown chart format "{fmt}".', f'Use one of: {", ".join(CHART_FORMATS)}.'
        )
