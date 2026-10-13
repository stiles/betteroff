"""Shared fixtures. Source files are synthetic: Michigan's usage agreement bars
redistributing real downloads, so tests build workbooks in the verified layout."""

from __future__ import annotations

import io
from collections.abc import Callable, Iterable, Sequence

import httpx
import pytest

from betteroff.cache import Cache
from betteroff.catalog import Question, load_catalog
from betteroff.fetch import Download

MONTH_NAMES = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
]
LANDING_URL = 'https://data.sca.isr.umich.edu/tables.php'

Row = tuple[int, int, Sequence[float | str | None]]


def gov_rows() -> list[Row]:
    """Two sparse early readings, then monthly 1978-01 through 1979-12."""
    rows: list[Row] = [(1961, 5, [36, 31, 9, 24]), (1970, 8, [18, 45, 26, 11])]
    for i in range(24):
        year, month = 1978 + i // 12, i % 12 + 1
        good = 20 + i % 5
        fair = 30
        dk = 2
        rows.append((year, month, [good, fair, 100 - good - fair - dk, dk]))
    return rows


def build_xls(
    question: Question,
    rows: Iterable[Row],
    *,
    labels: Sequence[str] | None = None,
    stacked: Sequence[str] | None = None,
    wording: str | None = None,
    totals: dict[int, float] | None = None,
    relative: dict[int, float] | None = None,
    footer: Sequence[str] = (),
    header_row: int = 6,
) -> bytes:
    import xlwt

    book = xlwt.Workbook()
    sheet = book.add_sheet(f'REDBK{question.table}')
    text = wording if wording is not None else question.wording
    half = len(text) // 2
    cut = text.find(' ', half)
    sheet.write(1, 4, f'The question was: "{text[:cut]}')
    sheet.write(2, 4, f'{text[cut + 1 :]}"')
    labels = list(labels or [r.source_label for r in question.responses])
    if stacked:
        for c, lab in enumerate(stacked, start=2):
            if lab:
                sheet.write(header_row - 1, c, lab)
    header = ['Date  of  Survey', '', *labels, 'Total', 'Relative', 'Cases']
    for c, v in enumerate(header):
        if v:
            sheet.write(header_row, c, v)
    pos = [i for i, r in enumerate(question.responses) if r.polarity == 'positive']
    neg = [i for i, r in enumerate(question.responses) if r.polarity == 'negative']
    r = header_row + 2
    for n, (year, month, values) in enumerate(rows):
        sheet.write(r, 0, MONTH_NAMES[month - 1])
        sheet.write(r, 1, float(year))
        nums = [v for v in values if isinstance(v, int | float)]
        for c, v in enumerate(values, start=2):
            if v is not None:
                sheet.write(r, c, v)
        base = 2 + len(values)
        total = (totals or {}).get(n, float(sum(nums)))
        rel = (relative or {}).get(n)
        if rel is None and all(isinstance(values[i], int | float) for i in pos + neg):
            rel = float(sum(values[i] for i in pos) - sum(values[i] for i in neg) + 100)  # type: ignore[misc]
        sheet.write(r, base, total)
        if rel is not None:
            sheet.write(r, base + 1, rel)
        sheet.write(r, base + 2, 1000.0 + n)
        r += 1
    for line in footer:
        r += 1
        sheet.write(r, 0, line)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def landing_page(table: str = '34', href: str | None = None) -> str:
    href = href or f'get-table.php?c=RB&amp;y=2026&amp;m=8&amp;n={table}&amp;f=xls&amp;k=abc123'
    return f"""<html><body>
    <a data-doctype="table: pdf" data-docname="RB {table}" href="get-table.php?f=pdf">PDF</a>
    <a data-doctype="table: xls" data-docname="YB {table}" href="get-table.php?c=YB">Excel</a>
    <a data-doctype="table: xls" data-docname="RB {table}" href="{href}">Excel</a>
    </body></html>"""


@pytest.fixture
def catalog():
    return load_catalog()


@pytest.fixture
def gov(catalog) -> Question:
    return catalog.resolve('government_policy')


@pytest.fixture
def gov_xls(gov) -> bytes:
    return build_xls(gov, gov_rows())


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch) -> Cache:
    root = tmp_path / 'cache'
    monkeypatch.setenv('BETTEROFF_CACHE_DIR', str(root))
    monkeypatch.delenv('BETTEROFF_DEBUG', raising=False)
    return Cache(root)


class FakeSource:
    """Stands in for the network: returns queued downloads or raises queued errors."""

    def __init__(self) -> None:
        self.queue: list[bytes | Exception] = []
        self.calls = 0

    def __call__(self, question: Question, client: object = None) -> Download:
        self.calls += 1
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        url = f'https://data.sca.isr.umich.edu/get-table.php?c=RB&y=2026&m=8&n={question.table}'
        return Download(content=item, url=url, source_period='2026-08')


@pytest.fixture
def source(monkeypatch) -> FakeSource:
    fake = FakeSource()
    monkeypatch.setattr('betteroff.api._fetch', fake)
    return fake


def mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
