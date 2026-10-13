import json
from pathlib import Path

import pandas as pd
import pytest

from betteroff import api
from betteroff.charts import chart_format
from betteroff.errors import InputError
from betteroff.export import (
    check_writable,
    data_format,
    render_data,
    resolve_format,
    sidecar,
    sidecar_path,
)


@pytest.fixture
def ds(source, gov_xls):
    source.queue = [gov_xls]
    return api.get('government_policy')


def test_tidy_contract(ds):
    data = ds.data
    assert list(data.columns) == [
        'date',
        'question_id',
        'measure',
        'response_id',
        'response_label',
        'value',
        'unit',
        'cases',
        'population',
    ]
    first = data.iloc[:4]
    assert list(first['response_id']) == ['good_job', 'fair', 'poor_job', 'dk_na']
    assert list(first['response_label']) == ['Good Job', 'Fair', 'Poor Job', 'DK, NA']
    assert set(data['unit']) == {'percent'}
    assert set(data['population']) == {'all_households'}
    assert not data.duplicated(['date', 'response_id']).any()


def test_wide_follows_catalog_order(ds):
    assert list(ds.wide().columns) == ['date', 'good_job', 'fair', 'poor_job', 'dk_na', 'cases']


def test_index_measure(source, gov_xls):
    source.queue = [gov_xls]
    ds = api.get('34', measure='index')
    assert set(ds.data['response_id']) == {'index'}
    assert set(ds.data['unit']) == {'index'}
    assert list(ds.wide().columns) == ['date', 'index', 'cases']


def test_start_end_trim(source, gov_xls):
    source.queue = [gov_xls]
    ds = api.get('34', start='1978-06', end='1979-02')
    dates = ds.wide()['date']
    assert dates.min() == pd.Timestamp('1978-06-01')
    assert dates.max() == pd.Timestamp('1979-02-01')


def test_bad_dates_and_measures(source, gov_xls):
    source.queue = [gov_xls]
    with pytest.raises(InputError, match='YYYY'):
        api.get('34', start='June 1978')
    with pytest.raises(InputError, match='measure'):
        api.get('34', measure='mean')
    with pytest.raises(InputError, match='after'):
        api.get('34', start='1979', end='1978')


def test_csv_keeps_precision_and_nulls(ds):
    text = render_data(ds, 'csv', wide=True)
    lines = text.splitlines()
    assert lines[0] == 'date,good_job,fair,poor_job,dk_na,cases'
    assert lines[1] == '1961-05-01,36,31,9,24,1000'


def test_json_records(ds):
    records = json.loads(render_data(ds, 'json', wide=False))
    assert records[0] == {
        'date': '1961-05-01',
        'question_id': 'government_policy',
        'measure': 'share',
        'response_id': 'good_job',
        'response_label': 'Good Job',
        'value': 36.0,
        'unit': 'percent',
        'cases': 1000,
        'population': 'all_households',
    }


def test_sidecar_contents(ds, tmp_path):
    out = tmp_path / 'gov.csv'
    meta = sidecar(ds, out, {'format': 'csv', 'wide': False})
    assert sidecar_path(out).name == 'gov.csv.meta.json'
    assert meta['question']['wording'].startswith('As to the economic policy')
    assert meta['source']['publisher'].startswith('University of Michigan')
    assert meta['snapshot']['sha256']
    assert meta['coverage']['latest_period'] == '1979-12'
    assert meta['source']['release_status'] == 'unknown'
    assert meta['export']['file'] == 'gov.csv'


@pytest.mark.parametrize(
    ('path', 'requested', 'expected'),
    [('a.csv', None, 'csv'), ('a.JSON', None, 'json'), ('a.csv', 'csv', 'csv')],
)
def test_resolve_data_format(path, requested, expected):
    assert resolve_format(Path(path), requested, ('csv', 'json'), data_format, 'csv') == expected


def test_format_extension_conflict():
    with pytest.raises(InputError, match='contradicts'):
        resolve_format(Path('a.csv'), 'json', ('csv', 'json'), data_format, 'csv')
    with pytest.raises(InputError, match='Cannot tell'):
        resolve_format(Path('a.txt'), None, ('csv', 'json'), data_format, 'csv')


def test_chart_format_inference():
    assert chart_format(Path('x.vl.json')) == 'vl.json'
    assert chart_format(Path('x.SVG')) == 'svg'
    assert chart_format(Path('x.json')) is None


def test_refuses_overwrite(tmp_path):
    target = tmp_path / 'x.csv'
    target.write_text('old')
    with pytest.raises(InputError, match='--force'):
        check_writable(target, force=False)
    check_writable(target, force=True)
