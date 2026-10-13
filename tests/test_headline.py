"""Headline indexes from the main site's CSV files. Files here are synthetic."""

from __future__ import annotations

import json
import warnings

import httpx
import pytest

from betteroff import api
from betteroff.api import BetteroffWarning
from betteroff.cache import Cache, bundle
from betteroff.catalog import load_catalog
from betteroff.errors import FetchError, InputError, ValidationError
from betteroff.fetch import download_index
from betteroff.parsers.headline import parse
from betteroff.validate import validate

from .conftest import MONTH_NAMES, mock_client

ICS = load_catalog().resolve('consumer_sentiment')
ICE = load_catalog().resolve('consumer_expectations')


def months(start: tuple[int, int], n: int) -> list[tuple[int, int]]:
    y, m = start
    out = []
    for _ in range(n):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def history_csv(rows, header='Month,YYYY,ICS_ALL') -> str:
    lines = [header] + [f'{MONTH_NAMES[m - 1]},{y},{v}' for (y, m), v in rows]
    return '\r\n'.join(lines) + '\r\n'


def current_csv(rows, column='INDEX OF CONSUMER SENTIMENT', prelim=None) -> str:
    """rows: ((year, month), value); prelim: ((year, month), value) marked (P)."""
    pad = ',' * 10
    lines = [
        f',,,THE INDEX OF CONSUMER SENTIMENT,{pad}',
        f',,,,{pad}',
        f'DATE OF SURVEY,,,,{column},{pad}',
        f',,,,{pad}',
    ]
    lines += [f'{MONTH_NAMES[m - 1]},{y},,,{v},{pad}' for (y, m), v in rows]
    if prelim:
        (y, m), v = prelim
        lines.append(f'{MONTH_NAMES[m - 1]} (P),{y},,,{v},{pad}')
    lines.append(f',,,,{pad}')
    return '\n'.join(lines) + '\n'


HISTORY = list(zip(months((1978, 1), 24), [80 + i % 7 for i in range(24)], strict=True))
RECENT = HISTORY[-12:]
PRELIM = ((1980, 1), 77.5)


def ics_bundle(history=HISTORY, recent=RECENT, prelim=PRELIM, **kwargs) -> bytes:
    src = ICS.source
    assert src is not None
    return bundle(
        {
            src.history_url: history_csv(history, **kwargs),
            src.current_url: current_csv(recent, prelim=prelim),
        }
    )


@pytest.fixture
def index_source(monkeypatch):
    from .conftest import FakeSource

    fake = FakeSource()
    monkeypatch.setattr('betteroff.api._fetch', fake)
    return fake


# Parsing


def test_parse_joins_history_and_preliminary():
    frame = parse(ics_bundle(), ICS).frame
    assert list(frame.columns) == ['date', 'index', 'preliminary']
    assert len(frame) == 25
    assert frame['preliminary'].tolist() == [False] * 24 + [True]
    assert frame.iloc[-1]['index'] == 77.5
    assert frame.iloc[0]['index'] == 80


def test_current_final_not_yet_in_history_is_added():
    newer = ((1980, 1), 79.0)
    frame = parse(ics_bundle(recent=[*RECENT, newer], prelim=((1980, 2), 76.0)), ICS).frame
    assert frame.iloc[-2][['index', 'preliminary']].tolist() == [79.0, False]
    assert frame.iloc[-1][['index', 'preliminary']].tolist() == [76.0, True]


def test_no_preliminary_between_releases():
    frame = parse(ics_bundle(prelim=None), ICS).frame
    assert not frame['preliminary'].any()


def test_history_wins_when_both_files_have_a_month():
    # On final-release day the history file can be updated before the current file.
    frame = parse(ics_bundle(prelim=(HISTORY[-1][0], 70.0)), ICS).frame
    assert not frame['preliminary'].any()
    assert frame.iloc[-1]['index'] == HISTORY[-1][1]


def test_disagreement_between_files_is_flagged():
    changed = [*RECENT[:-1], (RECENT[-1][0], 99.9)]
    parsed = parse(ics_bundle(recent=changed), ICS)
    assert [f['check'] for f in parsed.flags] == ['current_file_differs']
    assert parsed.frame.iloc[-2]['index'] == HISTORY[-1][1]


def test_blank_values_before_an_index_began_are_dropped():
    src = ICE.source
    assert src is not None
    history = 'Month,YYYY,ICC,ICE\r\nFebruary,1951,67.7,\r\nMay,1951,60.2,75.0\r\n'
    recent = current_csv([((1951, 5), 75.0)], column='EXPECTED INDEX  ')
    frame = parse(bundle({src.history_url: history, src.current_url: recent}), ICE).frame
    assert frame['date'].dt.strftime('%Y-%m').tolist() == ['1951-05']


@pytest.mark.parametrize(
    ('kwargs', 'match'),
    [
        ({'header': 'Month,Year,ICS_ALL'}, 'Month,YYYY'),
        ({'header': 'Month,YYYY,ICS'}, 'no "ICS_ALL" column'),
    ],
)
def test_layout_changes_fail(kwargs, match):
    with pytest.raises(ValidationError, match=match):
        parse(ics_bundle(**kwargs), ICS)


def test_preliminary_older_than_a_final_fails():
    gap = [row for row in HISTORY if row[0] != (1979, 6)]
    with pytest.raises(ValidationError, match='older than the latest final'):
        parse(ics_bundle(history=gap, recent=gap[-11:], prelim=((1979, 6), 70.0)), ICS)


def test_two_preliminary_readings_fail():
    src = ICS.source
    assert src is not None
    text = current_csv(RECENT, prelim=((1980, 1), 70.0)) + 'February (P),1980,,,71.0\n'
    with pytest.raises(ValidationError, match='more than one preliminary'):
        parse(bundle({src.history_url: history_csv(HISTORY), src.current_url: text}), ICS)


def test_validation_rejects_impossible_values():
    parsed = parse(ics_bundle(prelim=((1980, 1), 250.0)), ICS)
    with pytest.raises(ValidationError, match='outside 0-200'):
        validate(parsed, ICS)


# Fetching


def test_download_index_rejects_html_and_dedupes_urls():
    calls = []

    def ok(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b'Month,YYYY,ICS_ALL\r\n')

    urls = ['https://example.test/a.csv', 'https://example.test/a.csv']
    download = download_index(urls, 'https://example.test/', client=mock_client(ok))
    assert calls == ['https://example.test/a.csv']
    assert json.loads(download.content) == {urls[0]: 'Month,YYYY,ICS_ALL\r\n'}

    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'<html><body>Not found</body></html>')

    with pytest.raises(FetchError, match='other than a CSV'):
        download_index(urls, 'https://example.test/', client=mock_client(html))


# API, revisions and cache


def test_get_returns_preliminary_flag_and_metadata(index_source, isolated_cache):
    index_source.queue = [ics_bundle()]
    ds = api.get('ICS')
    assert ds.measure == 'index'
    assert list(ds.wide().columns) == ['date', 'index', 'preliminary']
    tidy = ds.data
    assert 'cases' not in tidy and tidy['preliminary'].tolist()[-1] is True
    meta = ds.metadata
    assert meta['source']['release_status'] == 'preliminary'
    assert meta['coverage']['latest_preliminary'] is True
    assert meta['coverage']['latest_period'] == '1980-01'
    assert meta['question']['base'] == '1966 = 100'
    assert not any('embargo' in n for n in meta['notes'])
    snap = isolated_cache.latest('consumer_sentiment')
    assert snap is not None and snap.suffix == '.json'
    assert isolated_cache.snapshot_path(snap.sha256, '.json').exists()


def test_index_has_no_share_measure(index_source):
    with pytest.raises(InputError, match='no response shares'):
        api.get('ICS', measure='share')
    assert index_source.calls == 0


def test_final_reading_is_reported_as_finalized_not_revised(index_source, caplog):
    index_source.queue = [ics_bundle()]
    api.get('ICS')
    final = ((1980, 1), 78.1)
    index_source.queue = [ics_bundle(history=[*HISTORY, final], prelim=None)]
    with warnings.catch_warnings():
        warnings.simplefilter('error', BetteroffWarning)
        with caplog.at_level('INFO', logger='betteroff'):
            ds = api.get('ICS', refresh=True)
    rev = ds.metadata['revisions']
    assert rev['finalized'] == [{'month': '1980-01', 'preliminary': 77.5, 'final': 78.1}]
    assert rev['changed_months'] == []
    assert ds.metadata['source']['release_status'] == 'final'
    assert '1980-01 is now final at 78.1 (preliminary was 77.5)' in caplog.text


def test_revised_final_reading_still_warns(index_source):
    index_source.queue = [ics_bundle()]
    api.get('ICS')
    revised = [*HISTORY[:-1], (HISTORY[-1][0], 50.0)]
    index_source.queue = [ics_bundle(history=revised)]
    with pytest.warns(BetteroffWarning, match='revised 1 month'):
        api.get('ICS', refresh=True)


def test_offline_read_and_prune_keep_json_snapshots(index_source, isolated_cache):
    index_source.queue = [ics_bundle()]
    api.get('ICS')
    index_source.queue = [ics_bundle(prelim=((1980, 1), 76.0))]
    with pytest.warns(BetteroffWarning, match='revised 1 month'):  # Still preliminary
        api.get('ICS', refresh=True)
    with pytest.warns(BetteroffWarning, match='Offline'):
        assert api.get('ICS', offline=True).wide()['index'].iloc[-1] == 76.0
    result = isolated_cache.prune()
    assert len(result.removed) == 1 and result.removed[0].suffix == '.json'
    assert Cache(isolated_cache.root).latest('consumer_sentiment') is not None


# Charts


def chart_spec(ds, **kwargs):
    pytest.importorskip('altair')
    return ds.chart(**kwargs).to_dict()


def test_chart_marks_preliminary_month(index_source):
    index_source.queue = [ics_bundle()]
    spec = chart_spec(api.get('ICS'))
    assert spec['title']['subtitle'][0] == 'Index, 1966 = 100'
    assert 'January 1980 is a preliminary reading' in spec['title']['subtitle'][1]
    hollow = [
        la
        for la in spec['layer']
        if isinstance(la['mark'], dict) and la['mark'].get('fill') == 'white'
    ]
    assert len(hollow) == 1
    assert spec['datasets'][hollow[0]['data']['name']] == [
        {'date': '1980-01-01T00:00:00', 'value': 77.5}
    ]
    texts = [r['text'] for rows in spec['datasets'].values() for r in rows if 'text' in r]
    footer = next(t for t in texts if t.startswith('Source:'))
    assert footer.startswith(
        'Source: University of Michigan, Survey Research Center, Surveys of Consumers.'
    )


def test_chart_axis_fits_values_and_skips_note_out_of_range(index_source):
    index_source.queue = [ics_bundle()]
    ds = api.get('ICS')
    spec = chart_spec(ds, end='1979-12')
    line = next(
        la for la in spec['layer'] if la['mark'] == 'line' or la['mark'].get('type') == 'line'
    )
    assert line['encoding']['y']['scale']['domain'] == [80, 90]
    assert not any('preliminary' in s for s in spec['title']['subtitle'])


def test_chart_rejects_responses_for_an_index(index_source):
    index_source.queue = [ics_bundle()]
    with pytest.raises(InputError, match='no responses to choose'):
        api.get('ICS').chart(responses=['positive'])


# CLI and recipes


def test_cli_get_and_chart_for_an_index(index_source, tmp_path):
    from typer.testing import CliRunner

    from betteroff.cli import app

    runner = CliRunner()
    index_source.queue = [ics_bundle()]
    result = runner.invoke(app, ['get', 'ICS', '-f', 'csv'])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert 'preliminary' in lines[0].split(',') and 'cases' not in lines[0]
    assert lines[-1].endswith(',True,all_households')

    out = tmp_path / 'ics.vl.json'
    assert runner.invoke(app, ['chart', 'ICS', '-o', str(out)]).exit_code == 0
    meta = json.loads((tmp_path / 'ics.vl.json.meta.json').read_text())
    assert meta['coverage']['latest_preliminary'] is True

    calls = index_source.calls
    assert runner.invoke(app, ['chart', 'ICS', '--measure', 'share']).exit_code == 2
    assert runner.invoke(app, ['chart', 'ICS', '--responses', 'positive']).exit_code == 2
    assert index_source.calls == calls


def test_recipe_job_for_an_index(index_source, tmp_path):
    pytest.importorskip('altair')
    from betteroff.recipes import load_recipe, run_recipe

    recipe = tmp_path / 'betteroff.toml'
    recipe.write_text(
        'schema_version = 1\noutput_dir = "out"\n'
        '[[jobs]]\nquestion = "ICS"\ndata_formats = ["json"]\nchart_formats = ["vl.json"]\n'
    )
    assert load_recipe(recipe).jobs[0].measure == 'index'
    index_source.queue = [ics_bundle()]
    run_recipe(recipe)
    rows = json.loads((tmp_path / 'out' / 'consumer_sentiment.json').read_text())
    assert rows[-1]['preliminary'] is True
