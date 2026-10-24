"""Index breakdowns by respondent group (tables 2n to 5b). Workbooks here are synthetic."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

import pytest

from betteroff import api
from betteroff.api import BetteroffWarning
from betteroff.catalog import Response, load_catalog
from betteroff.errors import InputError, ValidationError
from betteroff.parsers.breakdown import parse
from betteroff.validate import validate

from .conftest import build_breakdown_xls, party_rows

CATALOG = load_catalog()
ICS_PARTY = CATALOG.resolve('consumer_sentiment_by_party')
ICC_PARTY = CATALOG.resolve('current_conditions_by_party')
ICE_PARTY = CATALOG.resolve('consumer_expectations_by_party')


def party_xls(**kwargs) -> bytes:
    return build_breakdown_xls(ICS_PARTY, kwargs.pop('rows', party_rows()), **kwargs)


# Catalog


BREAKDOWN_TABLES = {
    '2n': ('income', ['bottom_third', 'middle_third', 'top_third']),
    '3n': ('age', ['age_18_34', 'age_35_54', 'age_55_plus']),
    '4n': ('education', ['high_school_or_less', 'some_college', 'college_degree']),
    '5a': ('region', ['northeast', 'north_central', 'south', 'west']),
    '5b': ('party', ['democrat', 'independent', 'republican']),
}


@pytest.mark.parametrize('table', BREAKDOWN_TABLES)
def test_each_breakdown_table_has_one_entry_per_index(table):
    by, groups = BREAKDOWN_TABLES[table]
    entries = [q for q in CATALOG.questions if q.is_breakdown and q.table == table]
    assert [q.id for q in entries] == [
        f'{index}_by_{by}'
        for index in ('consumer_sentiment', 'current_conditions', 'consumer_expectations')
    ]
    for q in entries:
        assert q.breakdown is not None and q.breakdown.by == by
        assert [r.id for r in q.responses] == groups
        assert len(set(q.breakdown.colors)) == len(groups)
        assert q.notes
    assert CATALOG.resolve(table).id == f'consumer_sentiment_by_{by}'
    assert api.resolve('ICE', by).id == f'consumer_expectations_by_{by}'


def test_breakdown_dimensions_follow_the_catalog():
    assert CATALOG.breakdown_dimensions == ['income', 'age', 'education', 'region', 'party']


def test_one_entry_per_index_for_table_5b():
    entries = [q for q in CATALOG.questions if q.is_breakdown and q.table == '5b']
    assert [q.id for q in entries] == [
        'consumer_sentiment_by_party',
        'current_conditions_by_party',
        'consumer_expectations_by_party',
    ]
    for q in entries:
        assert q.table == '5b' and q.breakdown is not None
        assert [r.id for r in q.responses] == ['democrat', 'independent', 'republican']
        assert {r.polarity for r in q.responses} == {'group'}
        assert len(q.breakdown.colors) == len(q.responses)
        assert q.monthly_since == date(2017, 2, 1)
    assert ICC_PARTY.title == 'Index of Current Economic Conditions by political party'


@pytest.mark.parametrize(
    ('identifier', 'by', 'expected'),
    [
        ('ICS', 'party', 'consumer_sentiment_by_party'),
        ('current_conditions', 'Party', 'current_conditions_by_party'),
        ('ice', ' party ', 'consumer_expectations_by_party'),
        ('consumer_sentiment_by_party', 'party', 'consumer_sentiment_by_party'),
    ],
)
def test_by_resolves_headline_indexes(identifier, by, expected):
    assert api.resolve(identifier, by).id == expected


@pytest.mark.parametrize(
    ('identifier', 'expected'), [('5b', ICS_PARTY.id), ('icc_by_party', ICC_PARTY.id)]
)
def test_breakdowns_resolve_by_table_and_alias(identifier, expected):
    assert CATALOG.resolve(identifier).id == expected


def test_by_rejects_tables_and_unknown_groupings():
    with pytest.raises(InputError, match='only with the headline indexes'):
        api.resolve('34', 'party')
    with pytest.raises(InputError, match='No breakdown "gender"') as exc:
        api.resolve('ICS', 'gender')
    assert 'income, age, education, region, party' in exc.value.action


def test_search_finds_party_breakdowns():
    assert [q.id for q in CATALOG.search('republicans')] == [
        ICS_PARTY.id,
        ICC_PARTY.id,
        ICE_PARTY.id,
    ]


# Parser


@pytest.mark.parametrize(
    ('question', 'first'),
    [
        (ICS_PARTY, [50.0, 51.0, 52.0]),
        (ICC_PARTY, [60.0, 61.0, 62.0]),
        (ICE_PARTY, [70.0, 71.0, 72.0]),
    ],
)
def test_parses_each_index_block(question, first):
    parsed = parse(party_xls(), question)
    frame = parsed.frame
    assert list(frame.columns) == ['date', 'democrat', 'independent', 'republican']
    assert frame.iloc[0, 1:].tolist() == first
    assert frame['date'].iloc[0] == frame['date'].min()
    assert len(frame) == len(party_rows())
    assert parsed.wording is None


@pytest.mark.parametrize(
    ('identifier', 'top', 'bottom'),
    [
        ('2n', ['Bottom', 'Middle', 'Top'], ['Third', 'Third  ', 'Third']),
        ('4n', ['H.S.  ', 'Some', 'College'], ['or Less', 'College', 'Degree']),
    ],
)
def test_stacked_group_labels(identifier, top, bottom):
    """Tables 2n and 4n split labels over two rows, with stray spaces."""
    q = CATALOG.resolve(identifier)
    xls = build_breakdown_xls(q, party_rows(), labels=bottom, stacked=top)
    assert parse(xls, q).frame.iloc[0, 1:].tolist() == [50.0, 51.0, 52.0]


def test_four_group_region_layout():
    q = CATALOG.breakdown_of(CATALOG.resolve('ICE'), 'region')
    rows = [
        (y, m, [base + g for base in (50, 60, 70) for g in range(4)]) for y, m, _ in party_rows()
    ]
    frame = parse(build_breakdown_xls(q, rows), q).frame
    assert list(frame.columns) == ['date', 'northeast', 'north_central', 'south', 'west']
    assert frame.iloc[0, 1:].tolist() == [70.0, 71.0, 72.0, 73.0]


def test_ad_hoc_groups_parse_with_any_labels():
    q = replace(
        ICS_PARTY,
        responses=tuple(Response(f'g{i}', lab, lab, 'group') for i, lab in enumerate('ABC')),
    )
    xls = build_breakdown_xls(q, party_rows())
    assert parse(xls, q).frame.iloc[0, 1:].tolist() == [50.0, 51.0, 52.0]


@pytest.mark.parametrize(
    ('kwargs', 'match'),
    [
        ({'labels': ['DEM', 'IND', 'GOP']}, 'expected "DEM", "IND", "REP"'),
        ({'labels': ['DEM', 'IND', 'REP', 'OTH']}, 'expected "DEM", "IND", "REP"'),
        ({'banner': 'RESPONDENT PARTY ID'}, 'banner "RESPONDENT POLITICAL PARTY"'),
        (
            {'blocks': ['SENTIMENT INDEX', 'CURRENT INDEX', 'FUTURE INDEX']},
            'no row lists',
        ),
        ({'block_columns': [3, 9, 6]}, '"CURRENT INDEX" no longer sits over'),
    ],
)
def test_layout_changes_fail(kwargs, match):
    with pytest.raises(ValidationError, match=match):
        parse(party_xls(**kwargs), ICS_PARTY)


def test_duplicate_month_and_bad_values_fail():
    rows = party_rows()
    with pytest.raises(ValidationError, match='twice'):
        parse(party_xls(rows=[*rows, rows[-1]]), ICS_PARTY)
    bad = [*rows[:-1], (rows[-1][0], rows[-1][1], ['n/a', *rows[-1][2][1:]])]
    with pytest.raises(ValidationError, match='SENTIMENT INDEX DEM'):
        parse(party_xls(rows=bad), ICS_PARTY)


def test_footnotes_become_source_notes():
    parsed = parse(party_xls(footer=['NOTE: Party identification asked since 1980.']), ICS_PARTY)
    assert parsed.source_notes == ['NOTE: Party identification asked since 1980.']


# Validation


def test_gaps_before_monthly_start_are_not_flagged():
    assert validate(parse(party_xls(), ICS_PARTY), ICS_PARTY) == []


def test_missing_months_and_group_values_are_flagged():
    rows = party_rows()
    del rows[6]  # 2017-05
    y, m, values = rows[-1]
    rows[-1] = (y, m, [values[0], None, *values[2:]])
    flags = validate(parse(party_xls(rows=rows), ICS_PARTY), ICS_PARTY)
    assert {'date': '2017-05-01', 'check': 'missing_month', 'detail': 'no reading'} in flags
    assert {
        'date': '2018-01-01',
        'check': 'missing_group_value',
        'detail': 'no value for independent',
    } in flags


def test_missing_months_flagged_from_survey_start_without_monthly_since():
    q = CATALOG.breakdown_of(CATALOG.resolve('ICS'), 'age')
    assert q.monthly_since is None
    rows = [(1978 + i // 12, i % 12 + 1, [80.0] * 9) for i in range(14)]
    del rows[3]  # 1978-04
    flags = validate(parse(build_breakdown_xls(q, rows), q), q)
    assert [f['date'] for f in flags if f['check'] == 'missing_month'] == ['1978-04-01']


def test_impossible_values_fail():
    rows = party_rows()
    y, m, values = rows[-1]
    rows[-1] = (y, m, [250.0, *values[1:]])
    with pytest.raises(ValidationError, match='outside 0-200'):
        validate(parse(party_xls(rows=rows), ICS_PARTY), ICS_PARTY)
    with pytest.raises(ValidationError, match='in the future'):
        validate(parse(party_xls(), ICS_PARTY), ICS_PARTY, today=date(2017, 6, 1))


# API


def test_get_by_party(source, isolated_cache):
    source.queue = [party_xls()]
    ds = api.get('ICS', by='party')
    assert ds.question.id == 'consumer_sentiment_by_party' and ds.measure == 'index'
    assert list(ds.wide().columns) == ['date', 'democrat', 'independent', 'republican']
    tidy = ds.data
    assert list(tidy.columns) == [
        'date',
        'question_id',
        'measure',
        'response_id',
        'response_label',
        'value',
        'unit',
        'population',
    ]
    assert tidy['population'].head(3).tolist() == [
        'party:democrat',
        'party:independent',
        'party:republican',
    ]
    assert set(tidy['response_id']) == {'index'}
    assert tidy['response_label'].iloc[0] == 'Index of Consumer Sentiment'
    meta = ds.metadata
    assert meta['population'] == 'by_party'
    assert meta['question']['kind'] == 'breakdown'
    assert meta['question']['index'] == 'consumer_sentiment'
    assert meta['question']['groups'][2]['population'] == 'party:republican'
    assert meta['question']['base'] == '1966 = 100'
    assert meta['source']['table'] == '5b'
    assert meta['coverage']['monthly_since'] == '2017-02'
    assert any('embargo' in n for n in meta['notes'])
    assert any('DEM, IND and REP' in n for n in meta['notes'])
    assert isolated_cache.latest('consumer_sentiment_by_party') is not None


def test_get_rejects_other_measures_without_fetching(source):
    with pytest.raises(InputError, match='only index values'):
        api.get('ICS', by='party', measure='share')
    assert source.calls == 0


def test_revisions_compare_group_values(source):
    source.queue = [party_xls()]
    api.get('ICS', by='party')
    rows = party_rows()
    y, m, values = rows[-1]
    rows[-1] = (y, m, [values[0] + 1, *values[1:]])
    source.queue = [party_xls(rows=[*rows, (2018, 2, values)])]
    with pytest.warns(BetteroffWarning, match='revised 1 month'):
        ds = api.get('ICS', by='party', refresh=True)
    rev = ds.metadata['revisions']
    assert rev['appended_months'] == ['2018-02']
    assert rev['changed_months'] == ['2018-01'] and rev['changed_values'] == 1


# Charts


def chart_spec(ds, **kwargs):
    pytest.importorskip('altair')
    return ds.chart(**kwargs).to_dict()


def _line(spec):
    return next(
        la for la in spec['layer'] if la['mark'] == 'line' or la['mark'].get('type') == 'line'
    )


def test_chart_uses_group_colors_and_fitted_axis(source):
    source.queue = [party_xls()]
    spec = chart_spec(api.get('ICS', by='party'))
    assert spec['title']['text'] == 'Index of Consumer Sentiment by political party'
    assert spec['title']['subtitle'][0] == 'Index, 1966 = 100, by political party'
    line = _line(spec)
    color = line['encoding']['color']['scale']
    assert color['domain'] == ['Democrats', 'Independents', 'Republicans']
    assert color['range'] == list(ICS_PARTY.breakdown.colors)
    assert line['encoding']['y']['scale']['domain'] == [50, 60]
    # Default view starts when party readings became monthly.
    assert line['encoding']['x']['scale']['domain'][0]['year'] == 2017
    texts = [r['text'] for rows in spec['datasets'].values() for r in rows if 'text' in r]
    assert any(t.startswith('Source:') and 'table 5b.' in t for t in texts)


def test_chart_selects_groups(source):
    source.queue = [party_xls()]
    ds = api.get('ICS', by='party')
    spec = chart_spec(ds, responses='republican,democrat')
    assert _line(spec)['encoding']['color']['scale']['domain'] == ['Democrats', 'Republicans']
    assert 'Not shown: Independents' in spec['title']['subtitle']
    with pytest.raises(InputError, match='unknown group'):
        ds.chart(responses=['positive'])


def test_chart_with_early_readings_notes_gaps(source):
    source.queue = [party_xls()]
    spec = chart_spec(api.get('ICS', by='party'), start='2008')
    assert any('Gaps are months without a reading' in s for s in spec['title']['subtitle'])


# CLI and recipes


def test_cli_get_chart_and_describe_by_party(source, tmp_path):
    from typer.testing import CliRunner

    from betteroff.cli import app

    runner = CliRunner()
    source.queue = [party_xls()]
    result = runner.invoke(app, ['get', 'ICS', '--by', 'party', '-f', 'csv'])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].endswith(',unit,population') and 'cases' not in lines[0]
    assert lines[-1].endswith(',index,party:republican')

    wide = runner.invoke(app, ['get', 'ICS', '--by', 'party', '--wide', '-f', 'csv'])
    assert wide.stdout.splitlines()[0] == 'date,democrat,independent,republican'

    described = runner.invoke(app, ['describe', 'ICS', '--by', 'party'])
    assert described.exit_code == 0
    assert 'party:democrat' in described.stdout and 'Latest data' in described.stdout

    pytest.importorskip('altair')
    out = tmp_path / 'party.vl.json'
    result = runner.invoke(app, ['chart', 'ICS', '--by', 'party', '-o', str(out)])
    assert result.exit_code == 0, result.output
    meta = json.loads((tmp_path / 'party.vl.json.meta.json').read_text())
    assert meta['population'] == 'by_party'

    calls = source.calls
    assert runner.invoke(app, ['get', '34', '--by', 'party']).exit_code == 2
    assert runner.invoke(app, ['chart', 'ICS', '--by', 'gender']).exit_code == 2
    assert (
        runner.invoke(app, ['chart', 'ICS', '--by', 'party', '--responses', 'dem']).exit_code == 2
    )
    assert source.calls == calls


def test_recipe_job_by_party(source, tmp_path):
    pytest.importorskip('altair')
    from betteroff.recipes import load_recipe, run_recipe

    recipe = tmp_path / 'betteroff.toml'
    recipe.write_text(
        'schema_version = 1\noutput_dir = "out"\n'
        '[[jobs]]\nquestion = "ICE"\nby = "party"\nresponses = ["democrat", "republican"]\n'
        'data_formats = ["csv"]\nchart_formats = ["vl.json"]\n'
    )
    job = load_recipe(recipe).jobs[0]
    assert job.question == 'consumer_expectations_by_party' and job.measure == 'index'
    source.queue = [party_xls()]
    written = run_recipe(recipe)
    assert {p.name for p in written} >= {
        'consumer_expectations_by_party.csv',
        'consumer_expectations_by_party.vl.json',
    }
