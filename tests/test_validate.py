from datetime import date

import pytest

from betteroff.errors import ValidationError
from betteroff.parsers.historical import parse
from betteroff.validate import validate

from .conftest import build_xls, gov_rows


def test_share_out_of_range_fails(gov):
    rows = gov_rows()
    rows[2] = (rows[2][0], rows[2][1], [120, 0, 0, 0])
    with pytest.raises(ValidationError, match='outside 0-100'):
        validate(parse(build_xls(gov, rows), gov), gov)


def test_future_month_fails(gov, gov_xls):
    with pytest.raises(ValidationError, match='future'):
        validate(parse(gov_xls, gov), gov, today=date(1979, 6, 15))


def test_source_quirks_are_flagged_not_fatal(gov):
    rows = gov_rows()
    rows[4] = (rows[4][0], rows[4][1], [20, 30, 45, 0])  # sums to 95
    xls = build_xls(gov, rows, totals={4: 100.0}, relative={6: 150.0})
    flags = validate(parse(xls, gov), gov)
    checks = {(f['check'], f['date']) for f in flags}
    assert ('shares_do_not_sum_to_total', '1978-03-01') in checks
    assert ('index_does_not_match_shares', '1978-05-01') in checks


def test_wording_change_is_flagged(gov):
    xls = build_xls(gov, gov_rows(), wording='A completely different question?')
    flags = validate(parse(xls, gov), gov)
    assert flags[-1]['check'] == 'wording_changed'


def test_wording_compare_ignores_punctuation(gov):
    xls = build_xls(gov, gov_rows(), wording=gov.wording.replace('–', '--'))
    assert validate(parse(xls, gov), gov) == []
