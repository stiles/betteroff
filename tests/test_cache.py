import os
import threading
import time

import pytest

from betteroff import cache as cache_mod
from betteroff.cache import Cache, Snapshot
from betteroff.errors import FetchError, InputError


def snap(question_id: str, content: bytes) -> Snapshot:
    return Snapshot(
        sha256=Cache.digest(content),
        question_id=question_id,
        table='34',
        url='https://example.test/rb34.xls',
        source_period='2026-08',
        retrieved_at='2026-10-12T00:00:00+00:00',
        checked_at='2026-10-12T00:00:00+00:00',
        first_period='1978-01',
        latest_period='2026-08',
        observations=1,
        parser_version='1',
    )


def store_versions(cache: Cache, question_id: str, n: int) -> list[Snapshot]:
    out = []
    for i in range(n):
        content = f'{question_id} version {i}'.encode()
        out.append(cache.store(snap(question_id, content), content))
    return out


def test_prune_keeps_newest_and_latest(isolated_cache):
    versions = store_versions(isolated_cache, 'government_policy', 4)
    result = isolated_cache.prune(keep=2)
    kept = isolated_cache.snapshots('government_policy')
    assert [s.sha256 for s in kept] == [v.sha256 for v in versions[2:]]
    assert isolated_cache.latest('government_policy') == versions[-1]
    assert result.dropped_entries == 2
    assert sorted(p.stem for p in result.removed) == sorted(v.sha256 for v in versions[:2])
    assert not any(isolated_cache.snapshot_path(v.sha256).exists() for v in versions[:2])
    assert isolated_cache.read_bytes(versions[-1]) == b'government_policy version 3'


def test_prune_never_drops_latest_out_of_order(isolated_cache):
    old, new = store_versions(isolated_cache, 'government_policy', 2)
    isolated_cache.store(old, b'government_policy version 0')  # rechecked; now latest and last
    isolated_cache.prune(keep=1)
    assert [s.sha256 for s in isolated_cache.snapshots('government_policy')] == [old.sha256]
    assert not isolated_cache.snapshot_path(new.sha256).exists()


def test_prune_removes_orphan_files(isolated_cache):
    (kept,) = store_versions(isolated_cache, 'government_policy', 1)
    orphan = isolated_cache.snapshot_path('f' * 64)
    orphan.write_bytes(b'left behind')
    result = isolated_cache.prune()
    assert result.removed == [orphan] and result.dropped_entries == 0
    assert not orphan.exists()
    assert isolated_cache.snapshot_path(kept.sha256).exists()


def test_prune_dry_run_changes_nothing(isolated_cache):
    versions = store_versions(isolated_cache, 'government_policy', 3)
    manifest = isolated_cache.manifest_path.read_bytes()
    result = isolated_cache.prune(dry_run=True)
    assert len(result.removed) == 2 and result.bytes_freed > 0
    assert isolated_cache.manifest_path.read_bytes() == manifest
    assert all(isolated_cache.snapshot_path(v.sha256).exists() for v in versions)


def test_prune_rejects_keep_zero(isolated_cache):
    with pytest.raises(InputError):
        isolated_cache.prune(keep=0)


def test_prune_on_empty_cache(isolated_cache):
    result = isolated_cache.prune()
    assert result.removed == [] and result.dropped_entries == 0


def test_concurrent_stores_keep_every_entry(isolated_cache):
    ids = [f'question_{i}' for i in range(8)]
    barrier = threading.Barrier(len(ids))

    def worker(qid: str) -> None:
        barrier.wait()
        store_versions(Cache(isolated_cache.root), qid, 3)

    threads = [threading.Thread(target=worker, args=(q,)) for q in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(len(isolated_cache.snapshots(q)) == 3 for q in ids)
    assert not isolated_cache.lock_path.exists()


def test_held_lock_times_out(isolated_cache, monkeypatch):
    monkeypatch.setattr(cache_mod, 'LOCK_TIMEOUT', 0.1)
    isolated_cache.root.mkdir(parents=True)
    isolated_cache.lock_path.write_text('12345')
    with pytest.raises(FetchError, match='Another betteroff process'):
        store_versions(isolated_cache, 'government_policy', 1)


def test_stale_lock_is_cleared(isolated_cache):
    isolated_cache.root.mkdir(parents=True)
    isolated_cache.lock_path.write_text('12345')
    old = time.time() - cache_mod.LOCK_STALE_AFTER - 5
    os.utime(isolated_cache.lock_path, (old, old))
    store_versions(isolated_cache, 'government_policy', 1)
    assert isolated_cache.latest('government_policy') is not None
    assert not isolated_cache.lock_path.exists()
