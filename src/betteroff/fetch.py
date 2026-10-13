"""Network access: discover the current download link for a table and fetch it."""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from . import __version__
from .cache import bundle
from .errors import FetchError

OLE2_SIGNATURE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_RETRY_AFTER = 60.0
USER_AGENT = f'betteroff/{__version__} (+https://github.com/stiles/betteroff)'


@dataclass(frozen=True)
class Download:
    content: bytes
    url: str
    source_period: str | None  # Release period in the link, e.g. "2026-08"


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != 'a':
            return
        a = dict(attrs)
        name, href, doctype = a.get('data-docname'), a.get('href'), a.get('data-doctype')
        if name and href and doctype and doctype.endswith('xls'):
            self.links[re.sub(r'\s+', ' ', name.strip())] = href


def find_table_link(page: str, table: str, base_url: str) -> str:
    """Return the absolute URL of the historical Excel file for `table`."""
    parser = _LinkParser()
    parser.feed(page)
    href = parser.links.get(f'RB {table}')
    if not href:
        raise FetchError(
            f'Could not find a historical Excel link for table {table} on {base_url}.',
            'The page layout may have changed or the page may require a login; '
            'check it in a browser and report an issue if the table is listed.',
        )
    return urljoin(base_url, href)


def _source_period(url: str) -> str | None:
    q = parse_qs(urlparse(url).query)
    try:
        return f'{int(q["y"][0]):04d}-{int(q["m"][0]):02d}'
    except (KeyError, ValueError, IndexError):
        return None


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None and (after := response.headers.get('retry-after')):
        try:
            return min(float(after), MAX_RETRY_AFTER)
        except ValueError:
            pass
    return float(2**attempt)


def _get(client: httpx.Client, url: str) -> httpx.Response:
    last: str = ''
    for attempt in range(MAX_ATTEMPTS):
        response = None
        try:
            response = client.get(url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = f'{type(exc).__name__}: {exc}'
        else:
            if response.status_code not in RETRY_STATUSES:
                if response.is_error:
                    raise FetchError(
                        f'{url} returned HTTP {response.status_code}.',
                        'Try again later, or use --offline to read the last saved snapshot.',
                    )
                return response
            last = f'HTTP {response.status_code}'
        if attempt < MAX_ATTEMPTS - 1:
            delay = _retry_delay(response, attempt)
            print(f'Retrying {url} in {delay:.0f}s ({last})', file=sys.stderr)
            time.sleep(delay)
    raise FetchError(
        f'Could not reach {url} after {MAX_ATTEMPTS} attempts ({last}).',
        'Check your connection, or use --offline to read the last saved snapshot.',
    )


def check_excel(response: httpx.Response, url: str) -> None:
    content = response.content
    expected = response.headers.get('content-length')
    encoded = response.headers.get('content-encoding', 'identity') != 'identity'
    if expected and expected.isdigit() and not encoded and int(expected) != len(content):
        raise FetchError(
            f'Download from {url} was truncated ({len(content)} of {expected} bytes).',
            'Try again with --refresh.',
        )
    if not content.startswith(OLE2_SIGNATURE):
        snippet = content[:80].decode('utf-8', 'replace').strip().replace('\n', ' ')
        raise FetchError(
            f'{url} returned something other than an Excel file: "{snippet}".',
            'The download link may have expired or redirected to an access page. '
            'Try again with --refresh; if it persists, check the tables page in a browser.',
        )


def download_table(table: str, landing_url: str, client: httpx.Client | None = None) -> Download:
    """Find and download the historical Excel file for a published table."""
    own = client is None
    client = client or httpx.Client(
        timeout=TIMEOUT, follow_redirects=True, headers={'User-Agent': USER_AGENT}
    )
    try:
        page = _get(client, landing_url)
        url = find_table_link(page.text, table, str(page.url))
        response = _get(client, url)
        check_excel(response, url)
        return Download(content=response.content, url=url, source_period=_source_period(url))
    finally:
        if own:
            client.close()


def check_csv(response: httpx.Response, url: str) -> str:
    content = response.content
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('latin-1')
    head = text.lstrip()[:200].lower()
    if not head or head.startswith('<') or '<html' in head:
        snippet = text.strip()[:80].replace('\n', ' ')
        raise FetchError(
            f'{url} returned something other than a CSV file: "{snippet}".',
            'The file may have moved. Try again with --refresh; if it persists, check '
            'https://www.sca.isr.umich.edu/tables.html in a browser.',
        )
    return text


def download_index(urls: list[str], page_url: str, client: httpx.Client | None = None) -> Download:
    """Download a headline index's CSV files from Michigan's main site as one bundle."""
    own = client is None
    client = client or httpx.Client(
        timeout=TIMEOUT, follow_redirects=True, headers={'User-Agent': USER_AGENT}
    )
    try:
        files = {url: check_csv(_get(client, url), url) for url in dict.fromkeys(urls)}
        return Download(content=bundle(files), url=page_url, source_period=None)
    finally:
        if own:
            client.close()
