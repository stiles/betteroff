import httpx
import pytest

from betteroff import fetch
from betteroff.errors import FetchError
from betteroff.fetch import download_table, find_table_link

from .conftest import LANDING_URL, landing_page, mock_client


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(fetch.time, 'sleep', slept.append)
    return slept


def test_find_table_link_picks_historical_excel():
    url = find_table_link(landing_page('34'), '34', LANDING_URL)
    assert url == (
        'https://data.sca.isr.umich.edu/get-table.php?c=RB&y=2026&m=8&n=34&f=xls&k=abc123'
    )


def test_missing_link_fails():
    with pytest.raises(FetchError, match='table 35'):
        find_table_link(landing_page('34'), '35', LANDING_URL)


def _handler(file_response: httpx.Response):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith('tables.php'):
            return httpx.Response(200, text=landing_page('34'))
        return file_response

    return handle


def test_download_returns_bytes_and_period(gov_xls):
    client = mock_client(_handler(httpx.Response(200, content=gov_xls)))
    dl = download_table('34', LANDING_URL, client=client)
    assert dl.content == gov_xls
    assert dl.source_period == '2026-08'


def test_html_with_200_is_rejected():
    client = mock_client(_handler(httpx.Response(200, text='<html>Please log in</html>')))
    with pytest.raises(FetchError, match='something other than an Excel file'):
        download_table('34', LANDING_URL, client=client)


def test_not_found_body_with_200_is_rejected():
    client = mock_client(_handler(httpx.Response(200, text='Not Found<br/>')))
    with pytest.raises(FetchError, match='Not Found'):
        download_table('34', LANDING_URL, client=client)


def test_truncated_download_is_rejected(gov_xls):
    response = httpx.Response(
        200, content=gov_xls[:100], headers={'content-length': str(len(gov_xls))}
    )
    client = mock_client(_handler(response))
    with pytest.raises(FetchError, match='truncated'):
        download_table('34', LANDING_URL, client=client)


def test_timeouts_retry_then_fail(no_sleep):
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout('timed out', request=request)

    with pytest.raises(FetchError, match='after 3 attempts') as exc:
        download_table('34', LANDING_URL, client=mock_client(handle))
    assert len(calls) == 3
    assert no_sleep == [1.0, 2.0]
    assert exc.value.exit_code == 3


def test_retry_after_is_respected(gov_xls, no_sleep):
    attempts = {'n': 0}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith('tables.php'):
            attempts['n'] += 1
            if attempts['n'] == 1:
                return httpx.Response(503, headers={'retry-after': '7'})
            return httpx.Response(200, text=landing_page('34'))
        return httpx.Response(200, content=gov_xls)

    download_table('34', LANDING_URL, client=mock_client(handle))
    assert no_sleep == [7.0]


def test_client_errors_do_not_retry():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(FetchError, match='HTTP 404'):
        download_table('34', LANDING_URL, client=mock_client(handle))
