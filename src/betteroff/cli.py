"""Command-line interface. Heavy libraries are imported inside the commands that need them."""

from __future__ import annotations

import logging
import math
import os
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from typer.core import TyperGroup

from . import __version__
from .catalog import Question, load_catalog
from .errors import BetteroffError, InputError

if TYPE_CHECKING:
    from .models import Dataset

out = Console(highlight=False, soft_wrap=True)
err = Console(stderr=True, highlight=False, soft_wrap=True)
log = logging.getLogger('betteroff')
state = {'debug': False}


class BetteroffGroup(TyperGroup):
    """Turn package errors into a one-line message and the contract's exit code."""

    def invoke(self, ctx: Any) -> Any:
        try:
            return super().invoke(ctx)
        except BetteroffError as exc:
            if state['debug'] or os.environ.get('BETTEROFF_DEBUG'):
                raise
            err.print(f'[red]error:[/red] {escape(exc.message)}')
            if exc.action:
                err.print(f'  {escape(exc.action)}')
            raise typer.Exit(exc.exit_code) from None


app = typer.Typer(
    name='betteroff',
    cls=BetteroffGroup,
    help=(
        'Clean data and charts from the University of Michigan Surveys of Consumers.\n\n'
        'Independent project; not an official University of Michigan product.'
    ),
    epilog=(
        'Examples:\n\n'
        '  betteroff search government\n\n'
        '  betteroff get government_policy --wide -o government_policy.csv\n\n'
        '  betteroff chart 34 --rolling 12 --recessions -o government_policy.svg'
    ),
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode='rich',
    context_settings={'help_option_names': ['-h', '--help']},
)
cache_app = typer.Typer(help='Inspect the local cache of source snapshots.', no_args_is_help=True)
app.add_typer(cache_app, name='cache')

QuestionArg = Annotated[
    str,
    typer.Argument(
        help='Question id (e.g. government_policy) or table number (e.g. 34).', show_default=False
    ),
]
StartOpt = Annotated[str | None, typer.Option('--start', help='First month, YYYY or YYYY-MM.')]
EndOpt = Annotated[str | None, typer.Option('--end', help='Last month, YYYY or YYYY-MM.')]
RefreshOpt = Annotated[bool, typer.Option('--refresh', help='Force a check of the source.')]
OfflineOpt = Annotated[
    bool, typer.Option('--offline', help='Use the saved snapshot; never touch the network.')
]
MeasureOpt = Annotated[
    str,
    typer.Option('--measure', '-m', help='share (percent per response) or index (index score).'),
]
ForceOpt = Annotated[bool, typer.Option('--force', help='Overwrite an existing output file.')]
QuietOpt = Annotated[
    bool, typer.Option('--quiet', '-q', help='Hide notices; keep warnings that change meaning.')
]


class _StderrHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        err.print(f'[dim]{escape(record.getMessage())}[/dim]')


def _show_warning(
    message: Warning | str,
    category: type[Warning],
    filename: str,
    lineno: int,
    file: Any = None,
    line: str | None = None,
) -> None:
    err.print(f'[yellow]warning:[/yellow] {escape(str(message))}')


def _configure(quiet: bool) -> None:
    log.handlers[:] = [_StderrHandler()]
    log.setLevel(logging.WARNING if quiet else logging.INFO)
    log.propagate = False
    warnings.showwarning = _show_warning


def _version(value: bool) -> None:
    if value:
        out.print(f'betteroff {__version__}')
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        bool, typer.Option('--version', callback=_version, is_eager=True, help='Show version.')
    ] = False,
    debug: Annotated[
        bool, typer.Option('--debug', help='Show full tracebacks (or set BETTEROFF_DEBUG=1).')
    ] = False,
) -> None:
    state['debug'] = debug


def _question_rows(questions: list[Question]) -> None:
    if not out.is_terminal:
        for q in questions:
            sys.stdout.write(f'{q.table}\t{q.id}\t{q.title}\n')
        return
    table = Table(box=None, pad_edge=False, header_style='bold')
    table.add_column('Table', justify='right', style='dim')
    table.add_column('Id', style='cyan', no_wrap=True)
    table.add_column('Title')
    for q in questions:
        table.add_row(q.table, q.id, q.title)
    out.print(table)


@app.command('search')
def search_cmd(
    text: Annotated[str, typer.Argument(help='Words to find in titles, wording and keywords.')],
) -> None:
    """Search supported questions. Works offline.

    Example: betteroff search unemployment
    """
    results = load_catalog().search(text)
    if not results:
        err.print(f'No questions match "{text}". Run `betteroff list` to see them all.')
        return
    _question_rows(results)


@app.command('list')
def list_cmd() -> None:
    """List supported tables and identifiers. Works offline."""
    _question_rows(list(load_catalog().questions))


SPARK = '▁▂▃▄▅▆▇█'


def sparkline(values: list[float]) -> str:
    present = [v for v in values if not math.isnan(v)]
    if not present:
        return ''
    lo, hi = min(present), max(present)
    span = hi - lo or 1
    return ''.join(
        ' ' if math.isnan(v) else SPARK[min(int((v - lo) / span * (len(SPARK) - 1) + 0.5), 7)]
        for v in values
    )


def _fmt(value: Any) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ''
    if math.isnan(v):
        return '–'
    return f'{v:.0f}' if v == int(v) else f'{v:.1f}'


@app.command('describe')
def describe_cmd(
    question: QuestionArg,
    as_json: Annotated[bool, typer.Option('--json', help='Print catalog details as JSON.')] = False,
) -> None:
    """Show wording, responses, notes and, if cached, the latest values.

    Example: betteroff describe 34
    """
    catalog = load_catalog()
    q = catalog.resolve(question)
    if as_json:
        import json

        sys.stdout.write(json.dumps(q.to_dict(), indent=2) + '\n')
        return

    out.print(f'[bold]{escape(q.title)}[/bold]')
    out.print(f'[dim]Table {q.table} · id {q.id} · all households[/dim]\n')
    out.print(f'"{escape(q.wording)}"\n')
    table = Table(box=None, pad_edge=False, header_style='bold')
    table.add_column('Response id', style='cyan')
    table.add_column('Label')
    table.add_column('Source label', style='dim')
    table.add_column('Polarity', style='dim')
    for r in q.responses:
        table.add_row(r.id, r.label, r.source_label, r.polarity)
    out.print(table)
    out.print(
        f'\nUnits: percent of respondents per response. [bold]--measure index[/bold] gives the '
        f'{catalog.index_label.lower()}: {catalog.index_definition}'
    )

    from .cache import Cache

    snapshot = Cache().latest(q.id)
    if snapshot is not None:
        from .api import cached_dataset

        ds = cached_dataset(q)
        if ds is not None:
            _describe_recent(ds)
    else:
        out.print(f'\n[dim]No cached data yet. Run `betteroff get {q.id}` to fetch it.[/dim]')

    out.print('\n[bold]Notes[/bold]')
    for note in (*q.notes, *catalog.notes):
        out.print(f'• {escape(note)}')
    out.print(
        f"• Data are subject to Michigan's usage agreement ({catalog.agreement_url}): attribute to "
        f'"{catalog.attribution}"; redistribution and publication need written consent.'
    )


def _describe_recent(ds: Dataset) -> None:
    wide = ds.wide()
    recent = wide.tail(3)
    last24 = wide.tail(24)
    meta = ds.metadata
    out.print(
        f'\n[bold]Latest data[/bold] [dim](snapshot {meta["snapshot"]["id"]}, retrieved '
        f'{meta["snapshot"]["retrieved_at"]}; covers {meta["coverage"]["first_period"]} to '
        f'{meta["coverage"]["latest_period"]})[/dim]'
    )
    table = Table(box=None, pad_edge=False, header_style='bold')
    table.add_column('Response')
    for d in recent['date']:
        table.add_column(f'{d:%b %Y}', justify='right')
    table.add_column('Last 24 months', no_wrap=True)
    table.add_column('Range', style='dim', justify='right')
    for r in ds.question.responses:
        vals = [float(v) for v in last24[r.id]]
        present = [v for v in vals if not math.isnan(v)]
        rng = f'{_fmt(min(present))}–{_fmt(max(present))}' if present else ''
        table.add_row(r.label, *(_fmt(v) for v in recent[r.id]), sparkline(vals), rng)
    out.print(table)


def _load(
    question: str, refresh: bool, offline: bool, start: str | None, end: str | None, measure: str
) -> Dataset:
    from .api import get

    return get(question, refresh=refresh, offline=offline, start=start, end=end, measure=measure)


TABLE_ROWS = 24


@app.command('get')
def get_cmd(
    question: QuestionArg,
    output: Annotated[
        Path | None, typer.Option('--output', '-o', help='Write to a .csv or .json file.')
    ] = None,
    fmt: Annotated[str | None, typer.Option('--format', '-f', help='table, csv or json.')] = None,
    wide: Annotated[
        bool, typer.Option('--wide', help='One row per month, one column per response id.')
    ] = False,
    measure: MeasureOpt = 'share',
    start: StartOpt = None,
    end: EndOpt = None,
    refresh: RefreshOpt = False,
    offline: OfflineOpt = False,
    meta: Annotated[
        Path | None,
        typer.Option('--meta', help='Also write metadata JSON when printing to stdout.'),
    ] = None,
    force: ForceOpt = False,
    quiet: QuietOpt = False,
) -> None:
    """Fetch (or reuse cached) data, validate it and print or export it.

    Prints a table in a terminal and CSV when piped. A file written with -o gets a
    metadata sidecar next to it: gov.csv gets gov.csv.meta.json.

    Example: betteroff get government_policy --wide -o government_policy.csv
    """
    from .export import (
        DATA_FORMATS,
        check_writable,
        data_format,
        render_data,
        resolve_format,
        sidecar,
        sidecar_path,
        write_sidecar,
    )

    _configure(quiet)
    if output is not None:
        chosen = resolve_format(output, fmt, DATA_FORMATS, data_format, 'csv')
        check_writable(output, force)
    else:
        default = 'table' if out.is_terminal else 'csv'
        chosen = resolve_format(None, fmt, ('table', *DATA_FORMATS), data_format, default)
    if meta is not None:
        check_writable(meta, force)

    ds = _load(question, refresh, offline, start, end, measure)
    if output is not None:
        output.write_text(render_data(ds, chosen, wide), encoding='utf-8')
        side = sidecar_path(output)
        write_sidecar(side, sidecar(ds, output, {'format': chosen, 'wide': wide}))
        log.info('Wrote %s and %s (latest month %s).', output, side.name, ds.latest_period)
    elif chosen == 'table':
        _print_table(ds)
    else:
        sys.stdout.write(render_data(ds, chosen, wide))
    if meta is not None:
        write_sidecar(meta, sidecar(ds, None, {'format': chosen, 'wide': wide}))


def _print_table(ds: Dataset) -> None:
    wide = ds.wide()
    shown = wide.tail(TABLE_ROWS)
    if ds.measure == 'index':
        headers = {'index': load_catalog().index_label}
    else:
        headers = {r.id: r.label for r in ds.question.responses}
    table = Table(
        title=f'{ds.question.title} [dim](table {ds.question.table})[/dim]',
        title_justify='left',
        box=None,
        pad_edge=False,
        header_style='bold',
    )
    table.add_column('Month')
    for col in ds.value_columns:
        table.add_column(headers[col], justify='right')
    table.add_column('Cases', justify='right', style='dim')
    for _, row in shown.iterrows():
        table.add_row(
            f'{row["date"]:%Y-%m}', *(_fmt(row[c]) for c in ds.value_columns), _fmt(row['cases'])
        )
    out.print(table)
    unit = 'index score' if ds.measure == 'index' else 'percent of respondents'
    note = f'Values are {unit}. Latest month {ds.latest_period}.'
    if len(wide) > len(shown):
        note += f' Showing the last {len(shown)} of {len(wide)} months; use -o or pipe for all.'
    err.print(f'[dim]{note}[/dim]')


@app.command('chart')
def chart_cmd(
    question: QuestionArg,
    output: Annotated[
        Path | None,
        typer.Option(
            '--output', '-o', help='.html, .svg, .png, .pdf or .vl.json. Defaults to ID.html.'
        ),
    ] = None,
    fmt: Annotated[
        str | None, typer.Option('--format', '-f', help='html, svg, png, pdf or vl.json.')
    ] = None,
    rolling: Annotated[
        int | None, typer.Option('--rolling', help='Trailing average over N calendar months.')
    ] = None,
    no_raw: Annotated[
        bool, typer.Option('--no-raw', help='Hide monthly lines behind a rolling average.')
    ] = False,
    recessions: Annotated[
        bool, typer.Option('--recessions', help='Shade NBER recessions.')
    ] = False,
    measure: MeasureOpt = 'share',
    start: Annotated[
        str | None,
        typer.Option(
            '--start',
            help='First month shown. Defaults to the start of monthly data, usually 1978-01.',
        ),
    ] = None,
    end: EndOpt = None,
    width: Annotated[int | None, typer.Option('--width', help='Static width in px.')] = None,
    height: Annotated[int | None, typer.Option('--height', help='Static height in px.')] = None,
    theme: Annotated[
        str | None,
        typer.Option(
            '--theme', '-t', help='Color theme name or .toml file. See `betteroff themes`.'
        ),
    ] = None,
    font: Annotated[
        str | None,
        typer.Option(
            '--font', help='Font family for chart text. Defaults to $BETTEROFF_FONT, then Inter.'
        ),
    ] = None,
    refresh: RefreshOpt = False,
    offline: OfflineOpt = False,
    open_: Annotated[bool, typer.Option('--open', help='Open the result in a browser.')] = False,
    force: ForceOpt = False,
    quiet: QuietOpt = False,
) -> None:
    """Build an exploratory trend chart from the same data `get` returns.

    Example: betteroff chart government_policy --rolling 12 --recessions -o gov.svg
    """
    from .charts import (
        CHART_FORMATS,
        RECESSIONS_CHECKED,
        RECESSIONS_SOURCE,
        build_chart,
        chart_format,
        require_altair,
        resolve_font,
        save_chart,
    )
    from .export import check_writable, resolve_format, sidecar, sidecar_path, write_sidecar
    from .themes import load_theme

    _configure(quiet)
    require_altair()
    q = load_catalog().resolve(question)
    chosen_theme = load_theme(theme)
    chosen_font = resolve_font(font)
    if output is None:
        chosen = resolve_format(None, fmt, CHART_FORMATS, chart_format, 'html')
        output = Path(f'{q.id}.{chosen}')
    else:
        chosen = resolve_format(output, fmt, CHART_FORMATS, chart_format, 'html')
    check_writable(output, force)

    ds = _load(q.id, refresh, offline, None, None, measure)
    chart = build_chart(
        ds,
        rolling=rolling,
        raw=not no_raw,
        recessions=recessions,
        start=start,
        end=end,
        width=width,
        height=height,
        container=chosen == 'html' and width is None,
        theme=chosen_theme,
        font=chosen_font,
    )
    save_chart(chart, output, chosen)
    details: dict[str, Any] = {
        'format': chosen,
        'chart': {
            'rolling': rolling,
            'raw': not no_raw,
            'recessions': recessions,
            'start': start,
            'end': end,
            'theme': chosen_theme.record(),
            'font': chosen_font,
        },
    }
    if recessions:
        details['chart']['recession_dates'] = {
            'source': RECESSIONS_SOURCE,
            'checked': RECESSIONS_CHECKED,
        }
    side = sidecar_path(output)
    write_sidecar(side, sidecar(ds, output, details))
    log.info('Wrote %s and %s (latest month %s).', output, side.name, ds.latest_period)
    if open_:
        import webbrowser

        webbrowser.open(output.resolve().as_uri())


@app.command('themes')
def themes_cmd() -> None:
    """List chart color themes with swatches. Works offline.

    Example: betteroff chart 34 --theme brbg
    """
    from .themes import DEFAULT_THEME, list_themes

    available = list_themes()
    if not out.is_terminal:
        for th in available:
            sys.stdout.write(
                f'{th.name}\t{th.colors["positive"][0]}\t{th.colors["negative"][0]}\t'
                f'{th.description}\n'
            )
        return
    table = Table(box=None, pad_edge=False, header_style='bold')
    table.add_column('Theme', style='cyan', no_wrap=True)
    table.add_column('Colors', no_wrap=True)
    table.add_column('Description')
    for th in available:
        swatch = ' '.join(
            f'[on {th.colors[p][0]}]{" " * 4}[/]'
            for p in ('positive', 'neutral', 'negative', 'nonresponse')
        )
        name = f'{th.name} (default)' if th.name == DEFAULT_THEME else th.name
        table.add_row(name, swatch, escape(th.description))
    out.print(table)
    err.print(
        '[dim]Colors: positive, neutral, negative, nonresponse. '
        'Use one with `betteroff chart ID --theme NAME`, or pass a .toml file.[/dim]'
    )


@app.command('run')
def run_cmd(
    recipe: Annotated[Path, typer.Argument(help='TOML recipe file.')],
    refresh: RefreshOpt = False,
    offline: OfflineOpt = False,
    quiet: QuietOpt = False,
) -> None:
    """Reproduce exports and charts from a TOML recipe.

    Recipes overwrite only the files they declare and write betteroff-run.json
    with the snapshot behind each output.

    Example: betteroff run betteroff.toml --refresh
    """
    from .recipes import run_recipe

    _configure(quiet)
    if refresh and offline:
        raise InputError('--refresh and --offline cannot be used together.', 'Choose one.')
    written = run_recipe(recipe, refresh=refresh, offline=offline)
    log.info('Recipe finished: %d file(s).', len(written))


@cache_app.command('info')
def cache_info() -> None:
    """Show cached snapshots, retrieval times and latest observation periods."""
    from .cache import Cache

    c = Cache()
    snaps = c.all_latest()
    if not snaps:
        err.print(f'No cached data in {c.root}.')
        return
    columns = (
        'Id',
        'Table',
        'Latest month',
        'Retrieved (UTC)',
        'Last checked (UTC)',
        'Snapshot',
        'Versions',
    )
    rows = [
        (
            s.question_id,
            s.table,
            s.latest_period,
            s.retrieved_at.replace('+00:00', ''),
            s.checked_at.replace('+00:00', ''),
            s.id,
            str(len(c.snapshots(s.question_id))),
        )
        for s in sorted(snaps, key=lambda s: int(s.table) if s.table.isdigit() else 0)
    ]
    if not out.is_terminal:
        for row in (columns, *rows):
            sys.stdout.write('\t'.join(row) + '\n')
        return
    table = Table(box=None, pad_edge=False, header_style='bold')
    for col in columns:
        table.add_column(col, no_wrap=True)
    for row in rows:
        table.add_row(*row)
    out.print(table)
    err.print(
        '[dim]Latest month is the newest survey month in the source; Michigan posts detailed '
        'tables about four weeks after each final release.[/dim]'
    )


@cache_app.command('prune')
def cache_prune(
    keep: Annotated[
        int, typer.Option('--keep', help='Snapshots to keep per question, newest first.')
    ] = 1,
    dry_run: Annotated[
        bool, typer.Option('--dry-run', help='List what would be deleted without deleting it.')
    ] = False,
) -> None:
    """Delete older snapshots. The latest snapshot for each question is always kept.

    Example: betteroff cache prune --keep 3 --dry-run
    """
    from .cache import Cache

    result = Cache().prune(keep=keep, dry_run=dry_run)
    for path in result.removed:
        sys.stdout.write(f'{path}\n')
    verb = 'Would remove' if dry_run else 'Removed'
    err.print(
        f'{verb} {len(result.removed)} snapshot file(s) ({result.bytes_freed / 1e6:.1f} MB) '
        f'and {result.dropped_entries} manifest record(s).'
    )


@cache_app.command('path')
def cache_path() -> None:
    """Print the cache directory (override with BETTEROFF_CACHE_DIR)."""
    from .cache import cache_dir

    sys.stdout.write(f'{cache_dir()}\n')


def main() -> None:
    app()
