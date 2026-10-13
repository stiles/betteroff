import warnings

import pytest

from betteroff import api
from betteroff.api import BetteroffWarning
from betteroff.cache import Cache
from betteroff.errors import FetchError, InputError, ValidationError

from .conftest import build_xls, gov_rows


def test_first_get_fetches_and_caches(source, gov_xls, isolated_cache):
    source.queue = [gov_xls]
    ds = api.get('34')
    assert source.calls == 1
    assert ds.metadata['snapshot']['mode'] == 'fresh'
    assert ds.metadata['coverage']['latest_period'] == '1979-12'
    snap = isolated_cache.latest('government_policy')
    assert snap is not None and snap.sha256 == Cache.digest(gov_xls)
    assert isolated_cache.snapshot_path(snap.sha256).read_bytes() == gov_xls


def test_fresh_cache_skips_network(source, gov_xls):
    source.queue = [gov_xls]
    api.get('government_policy')
    ds = api.get('government_policy')
    assert source.calls == 1
    assert ds.metadata['snapshot']['mode'] == 'cached'


def test_failed_refresh_fails_and_keeps_snapshot(source, gov_xls, isolated_cache):
    source.queue = [gov_xls]
    api.get('34')
    before = isolated_cache.latest('government_policy')
    source.queue = [FetchError('down')]
    with pytest.raises(FetchError):
        api.get('34', refresh=True)
    assert isolated_cache.latest('government_policy') == before


def test_invalid_refresh_keeps_last_valid_snapshot(source, gov, gov_xls, isolated_cache):
    source.queue = [gov_xls]
    api.get('34')
    before = isolated_cache.latest('government_policy')
    bad = build_xls(gov, gov_rows(), labels=['Good', 'Fair', 'Poor', 'DK'])
    source.queue = [bad]
    with pytest.raises(ValidationError):
        api.get('34', refresh=True)
    assert isolated_cache.latest('government_policy') == before
    assert not isolated_cache.snapshot_path(Cache.digest(bad)).exists()


def test_expired_cache_falls_back_with_warning(source, gov_xls, isolated_cache, monkeypatch):
    source.queue = [gov_xls]
    api.get('34')
    monkeypatch.setattr('betteroff.cache.Snapshot.is_fresh', lambda self, now=None: False)
    source.queue = [FetchError('down')]
    with pytest.warns(BetteroffWarning, match='Could not reach the source'):
        ds = api.get('34')
    assert ds.metadata['snapshot']['mode'] == 'stale'


def test_offline_requires_snapshot(source):
    with pytest.raises(FetchError, match='No saved snapshot') as exc:
        api.get('34', offline=True)
    assert exc.value.exit_code == 3
    assert source.calls == 0


def test_offline_uses_snapshot_and_warns(source, gov_xls):
    source.queue = [gov_xls]
    api.get('34')
    with pytest.warns(BetteroffWarning, match='Offline'):
        ds = api.get('34', offline=True)
    assert source.calls == 1
    assert ds.metadata['snapshot']['mode'] == 'offline'


def test_refresh_and_offline_conflict(source):
    with pytest.raises(InputError):
        api.get('34', refresh=True, offline=True)


def test_unchanged_refresh_keeps_retrieval_time(source, gov_xls, isolated_cache):
    source.queue = [gov_xls]
    first = api.get('34').metadata['snapshot']
    second = api.get('34', refresh=True).metadata['snapshot']
    assert second['sha256'] == first['sha256']
    assert second['retrieved_at'] == first['retrieved_at']
    assert len(isolated_cache.snapshots('government_policy')) == 1


def test_revisions_are_reported(source, gov):
    rows = gov_rows()
    source.queue = [build_xls(gov, rows)]
    api.get('34')

    revised = list(rows)
    revised[3] = (revised[3][0], revised[3][1], [25, 30, 43, 2])  # 1978-02 revised
    del revised[0]  # 1961-05 removed
    revised.append((1980, 1, [30, 30, 38, 2]))  # appended
    source.queue = [build_xls(gov, revised)]
    with pytest.warns(BetteroffWarning, match='revised 1 month'):
        ds = api.get('34', refresh=True)
    rev = ds.metadata['revisions']
    assert rev['appended_months'] == ['1980-01']
    assert rev['removed_months'] == ['1961-05']
    assert rev['changed_months'] == ['1978-02']
    assert rev['changed_values'] == 3  # good_job, poor_job and the index
    assert len(Cache().snapshots('government_policy')) == 2


def test_wording_change_warns(source, gov):
    source.queue = [build_xls(gov, gov_rows(), wording='A different question?')]
    with pytest.warns(BetteroffWarning, match='wording'):
        ds = api.get('34')
    assert ds.metadata['quality_flags'][-1]['check'] == 'wording_changed'


def test_compare_treats_matching_nulls_as_equal(gov):
    rows = gov_rows()
    rows[5] = (rows[5][0], rows[5][1], [20, 30, None, 2])
    from betteroff.parsers.historical import parse

    frame = parse(build_xls(gov, rows), gov).frame
    rev = api.compare_snapshots(frame, frame.copy(), ['good_job', 'poor_job'])
    assert rev['changed_values'] == 0


def test_damaged_snapshot_is_detected(source, gov_xls, isolated_cache):
    source.queue = [gov_xls]
    api.get('34')
    snap = isolated_cache.latest('government_policy')
    isolated_cache.snapshot_path(snap.sha256).write_bytes(b'corrupt')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        with pytest.raises(FetchError, match='damaged'):
            api.get('34', offline=True)
