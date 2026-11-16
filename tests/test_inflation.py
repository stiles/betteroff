"""Inflation / price-expectations table parsing."""

from __future__ import annotations

import math
import re

import pytest
import xlrd

from betteroff.parsers.inflation import parse
from betteroff.validate import validate

from .conftest import build_inflation_xls, inflation_rows, raw_rows, source_number


def test_pre_1978_na_cells_parse_and_match_source(table32):
    """Table 32 marks Down and fine up-brackets as NA before January 1978."""
    content = build_inflation_xls(table32, inflation_rows())
    parsed = parse(content, table32)
    assert validate(parsed, table32) == []

    ids = [r.id for r in table32.responses]
    first = parsed.frame.loc[0]
    assert math.isnan(first['down'])
    assert first['same'] == 29
    assert first['up_1_to_2'] == 53
    assert math.isnan(first['up_3_to_4'])
    assert math.isnan(first['median'])
    assert first['dk_na'] == 18

    rows = raw_rows(content)
    source_values = [source_number(v) for v in rows[0][2 : 2 + len(ids)]]
    assert list(parsed.frame.loc[0, ids]) == pytest.approx(source_values, nan_ok=True)


def test_source_number_treats_na_as_missing():
    assert math.isnan(source_number('NA'))
    assert math.isnan(source_number('na'))
    assert math.isnan(source_number(''))
    assert source_number(12.5) == 12.5
    assert source_number('3.4') == 3.4


def test_raw_rows_skips_header(table32):
    content = build_inflation_xls(table32, inflation_rows())
    sheet = xlrd.open_workbook(file_contents=content).sheet_by_index(0)
    rows = raw_rows(content)
    assert rows
    assert all(isinstance(r[1], float) and re.match(r'[A-Z][a-z]+$', str(r[0])) for r in rows)
    assert len(rows) < sheet.nrows
