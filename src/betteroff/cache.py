"""Content-addressed snapshots of source downloads plus a JSON manifest."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .errors import FetchError, InputError

MANIFEST_VERSION = 1
FRESH_FOR = timedelta(hours=24)
LOCK_TIMEOUT = 10.0
LOCK_STALE_AFTER = 30.0  # Seconds; holders finish in milliseconds, so an older lock is a crash


def cache_dir() -> Path:
    env = os.environ.get('BETTEROFF_CACHE_DIR')
    if env:
        return Path(env).expanduser()
    from platformdirs import user_cache_path

    return user_cache_path('betteroff', appauthor=False)


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def bundle(files: dict[str, str]) -> bytes:
    """Several source files as one snapshot: JSON keyed by URL, stable byte for byte."""
    return json.dumps(files, sort_keys=True, ensure_ascii=False).encode('utf-8')


def unbundle(content: bytes) -> dict[str, str]:
    files = json.loads(content.decode('utf-8'))
    if not isinstance(files, dict):
        raise ValueError('not a snapshot bundle')
    return {str(k): str(v) for k, v in files.items()}


@dataclass
class Snapshot:
    sha256: str
    question_id: str
    table: str
    url: str
    source_period: str | None
    retrieved_at: str
    checked_at: str
    first_period: str
    latest_period: str
    observations: int
    parser_version: str
    suffix: str = '.xls'  # Headline indexes store a JSON bundle of CSV files

    @property
    def id(self) -> str:
        return self.sha256[:12]

    def is_fresh(self, now: datetime | None = None) -> bool:
        checked = datetime.fromisoformat(self.checked_at)
        return (now or now_utc()) - checked < FRESH_FOR


@dataclass
class PruneResult:
    removed: list[Path]
    bytes_freed: int
    dropped_entries: int


class Cache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or cache_dir()

    @property
    def manifest_path(self) -> Path:
        return self.root / 'manifest.json'

    @property
    def lock_path(self) -> Path:
        return self.root / 'manifest.lock'

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """Serialize manifest updates across processes, such as two recipe runs."""
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > LOCK_STALE_AFTER:
                    self.lock_path.unlink(missing_ok=True)
                    continue
                if time.monotonic() > deadline:
                    raise FetchError(
                        f'Another betteroff process is updating the cache ({self.lock_path}).',
                        'Wait for it to finish, or delete the lock file if none is running.',
                    ) from None
                time.sleep(0.05)
            else:
                break
        try:
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            yield
        finally:
            self.lock_path.unlink(missing_ok=True)

    def snapshot_path(self, sha256: str, suffix: str = '.xls') -> Path:
        return self.root / 'snapshots' / f'{sha256}{suffix}'

    def _read(self) -> dict:
        try:
            data = json.loads(self.manifest_path.read_text('utf-8'))
        except FileNotFoundError:
            return {'schema_version': MANIFEST_VERSION, 'questions': {}}
        except (OSError, json.JSONDecodeError) as exc:
            raise FetchError(
                f'The cache manifest at {self.manifest_path} is unreadable ({exc}).',
                'Delete the cache directory (see `betteroff cache path`) and run again.',
            ) from exc
        return data

    def _write(self, data: dict) -> None:
        _atomic_write(self.manifest_path, json.dumps(data, indent=2).encode('utf-8'))

    def snapshots(self, question_id: str) -> list[Snapshot]:
        entry = self._read()['questions'].get(question_id, {})
        return [Snapshot(**s) for s in entry.get('snapshots', [])]

    def latest(self, question_id: str) -> Snapshot | None:
        entry = self._read()['questions'].get(question_id)
        if not entry:
            return None
        for s in entry['snapshots']:
            if s['sha256'] == entry['latest']:
                return Snapshot(**s)
        return None

    def all_latest(self) -> list[Snapshot]:
        out = []
        for qid in self._read()['questions']:
            snap = self.latest(qid)
            if snap:
                out.append(snap)
        return out

    def read_bytes(self, snapshot: Snapshot) -> bytes:
        path = self.snapshot_path(snapshot.sha256, snapshot.suffix)
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            content = b''
        if hashlib.sha256(content).hexdigest() != snapshot.sha256:
            raise FetchError(
                f'The cached snapshot for {snapshot.question_id} is missing or damaged.',
                'Run the command again with --refresh.',
            )
        return content

    def store(self, snapshot: Snapshot, content: bytes) -> Snapshot:
        """Save validated bytes and make them the latest snapshot for the question."""
        path = self.snapshot_path(snapshot.sha256, snapshot.suffix)
        with self._lock():
            if not path.exists():
                _atomic_write(path, content)
            data = self._read()
            entry = data['questions'].setdefault(snapshot.question_id, {'snapshots': []})
            entry['snapshots'] = [s for s in entry['snapshots'] if s['sha256'] != snapshot.sha256]
            entry['snapshots'].append(asdict(snapshot))
            entry['latest'] = snapshot.sha256
            self._write(data)
        return snapshot

    def prune(self, keep: int = 1, dry_run: bool = False) -> PruneResult:
        """Keep the latest `keep` snapshots per question and delete unreferenced files.

        The latest snapshot is always kept. Snapshots are listed oldest first.
        """
        if keep < 1:
            raise InputError('--keep must be at least 1.', 'The latest snapshot is always kept.')
        with self._lock():
            data = self._read()
            dropped = 0
            for entry in data['questions'].values():
                snaps = entry['snapshots']
                cutoff = len(snaps) - keep
                kept = [
                    s for i, s in enumerate(snaps) if i >= cutoff or s['sha256'] == entry['latest']
                ]
                dropped += len(snaps) - len(kept)
                entry['snapshots'] = kept
            referenced = {s['sha256'] for e in data['questions'].values() for s in e['snapshots']}
            folder = self.root / 'snapshots'
            files = (
                sorted(f for f in folder.iterdir() if f.is_file() and not f.name.startswith('.'))
                if folder.is_dir()
                else []
            )
            removed = [f for f in files if f.stem not in referenced]
            freed = sum(f.stat().st_size for f in removed)
            if not dry_run:
                if dropped:
                    self._write(data)
                for f in removed:
                    f.unlink(missing_ok=True)
        return PruneResult(removed=removed, bytes_freed=freed, dropped_entries=dropped)

    @staticmethod
    def digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()
