"""Live checks against Michigan's site. Run sparingly: `uv run pytest -m live`.

Nothing downloaded here is written to the repository.
"""

from __future__ import annotations

import re
import time

import httpx
import pytest
import xlrd

from betteroff.catalog import load_catalog
from betteroff.fetch import TIMEOUT, USER_AGENT, download_table
from betteroff.parsers.historical import parse
from betteroff.validate import validate

pytestmark = pytest.mark.live
CATALOG = load_catalog()


@pytest.fixture(scope='module')
def client():
    with httpx.Client(
        timeout=TIMEOUT, follow_redirects=True, headers={'User-Agent': USER_AGENT}
    ) as c:
        yield c


def raw_rows(content: bytes) -> list[list[object]]:
    """Read data rows straight from the workbook, without the parser's mapping logic."""
    sheet = xlrd.open_workbook(file_contents=content).sheet_by_index(0)
    rows = [sheet.row_values(r) for r in range(sheet.nrows)]
    return [r for r in rows if isinstance(r[1], float) and re.match(r'[A-Z][a-z]+$', str(r[0]))]


TABLES = [q for q in CATALOG.questions if not q.is_index]


@pytest.mark.parametrize('question', TABLES, ids=lambda q: f'{q.table}-{q.id}')
def test_table_parses_validates_and_matches_source(client, question):
    download = download_table(question.table, CATALOG.landing_url, client=client)
    parsed = parse(download.content, question)
    flags = validate(parsed, question)
    assert not [f for f in flags if f['check'] == 'wording_changed'], flags

    rows = raw_rows(download.content)
    frame = parsed.frame
    assert len(rows) == len(frame)
    ids = [r.id for r in question.responses]
    for i in (0, len(rows) // 2, len(rows) - 1):
        source_values = [float(v) for v in rows[i][2 : 2 + len(ids)]]
        assert list(frame.loc[i, ids]) == source_values, (question.id, rows[i][:2])
        assert int(rows[i][1]) == frame.loc[i, 'date'].year
    time.sleep(1)


INDEXES = [q for q in CATALOG.questions if q.is_index]
# Column of each index in the data site's historical tables 1a and 1b, as a cross-check.
DATA_SITE_COLUMNS = {'ICS': ('1a', 2), 'ICC': ('1b', 2), 'ICE': ('1b', 5)}


@pytest.mark.parametrize('question', INDEXES, ids=lambda q: q.table)
def test_headline_index_matches_the_data_site(client, question):
    from datetime import date

    from betteroff.fetch import download_index
    from betteroff.parsers.headline import parse as parse_index

    assert question.source is not None
    urls = [question.source.history_url, question.source.current_url]
    download = download_index(urls, CATALOG.headline.page_url, client=client)
    parsed = parse_index(download.content, question)
    flags = validate(parsed, question)
    assert not flags, flags
    frame = parsed.frame
    today = date.today()
    latest = frame['date'].max().date()
    assert (today.year - latest.year) * 12 + today.month - latest.month <= 2

    table, col = DATA_SITE_COLUMNS[question.table]
    rows = raw_rows(download_table(table, CATALOG.landing_url, client=client).content)
    data_site = {(int(r[1]), r[0][:3]): float(r[col]) for r in rows if isinstance(r[col], float)}
    finals = frame[~frame['preliminary']]
    compared = 0
    for when, value in zip(finals['date'], finals['index'], strict=True):
        key = (when.year, f'{when:%b}')
        if key in data_site:
            assert value == pytest.approx(data_site[key], abs=0.05), (question.table, key)
            compared += 1
    assert compared > 500
    time.sleep(1)
