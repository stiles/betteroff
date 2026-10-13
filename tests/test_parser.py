import math

import pytest

from betteroff.errors import ValidationError
from betteroff.parsers.historical import parse
from betteroff.validate import validate

from .conftest import build_xls, gov_rows


def test_parses_verified_layout(gov, gov_xls):
    parsed = parse(gov_xls, gov)
    f = parsed.frame
    assert list(f.columns) == [
        'date',
        'good_job',
        'fair',
        'poor_job',
        'dk_na',
        'total',
        'index',
        'cases',
    ]
    assert len(f) == 26
    assert f['date'].iloc[0].isoformat()[:10] == '1961-05-01'
    assert f['date'].iloc[-1].isoformat()[:10] == '1979-12-01'
    first = f.iloc[0]
    assert (first.good_job, first.fair, first.poor_job, first.dk_na) == (36, 31, 9, 24)
    assert first['index'] == 36 - 9 + 100
    assert parsed.wording == gov.wording
    assert validate(parsed, gov) == []


def test_missing_values_stay_missing(gov):
    rows = gov_rows()
    rows[5] = (rows[5][0], rows[5][1], [20, 30, None, 2])
    parsed = parse(build_xls(gov, rows), gov)
    assert math.isnan(parsed.frame.loc[5, 'poor_job'])
    assert parsed.frame.loc[5, 'good_job'] == 20


def test_unexpected_header_fails(gov):
    labels = ['Good Job', 'Fair', 'Bad Job', 'DK, NA']
    with pytest.raises(ValidationError, match='headers changed') as exc:
        parse(build_xls(gov, gov_rows(), labels=labels), gov)
    assert 'Bad Job' in str(exc.value)
    assert exc.value.exit_code == 4


def test_extra_column_fails(gov):
    rows = [(y, m, [*v, 0]) for y, m, v in gov_rows()]
    labels = ['Good Job', 'Fair', 'Poor Job', 'DK, NA', 'Refused']
    with pytest.raises(ValidationError, match='Refused'):
        parse(build_xls(gov, rows, labels=labels), gov)


def test_duplicate_month_fails(gov):
    rows = gov_rows()
    rows.append(rows[-1])
    with pytest.raises(ValidationError, match='twice'):
        parse(build_xls(gov, rows), gov)


def test_unknown_code_fails(gov):
    rows = gov_rows()
    rows[3] = (rows[3][0], rows[3][1], [20, 30, 48, '*'])
    with pytest.raises(ValidationError, match=r"Unexpected value '\*'"):
        parse(build_xls(gov, rows), gov)


def test_footnotes_become_source_notes(gov):
    xls = build_xls(gov, gov_rows(), footer=['*: Less than half of one percent.'])
    assert parse(xls, gov).source_notes == ['*: Less than half of one percent.']


def test_stacked_headers(catalog):
    q = catalog.resolve('real_income_expectations')
    rows = [(1980, m, [20, 35, 40, 5]) for m in range(1, 7)]
    xls = build_xls(
        q,
        rows,
        labels=['Up More', 'Up Same', 'Up More', 'DK, NA'],
        stacked=['Income', 'Income', 'Prices'],
    )
    parsed = parse(xls, q)
    assert list(parsed.frame.columns[1:5]) == ['income_more', 'same', 'prices_more', 'dk_na']
    assert parsed.frame['index'].iloc[0] == 80
    assert parsed.wording == q.wording


def test_tables_without_nonresponse_column(catalog):
    q = catalog.resolve('durables_buying_conditions')
    xls = build_xls(q, [(1990, m, [50, 10, 40]) for m in range(1, 4)])
    assert list(parse(xls, q).frame.columns) == [
        'date',
        'good_time',
        'uncertain',
        'bad_time',
        'total',
        'index',
        'cases',
    ]


def test_not_an_excel_file(gov):
    with pytest.raises(ValidationError, match='Could not read'):
        parse(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 truncated', gov)
