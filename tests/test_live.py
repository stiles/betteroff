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


@pytest.mark.parametrize('question', CATALOG.questions, ids=lambda q: f'{q.table}-{q.id}')
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
