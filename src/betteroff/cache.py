"""Content-addressed snapshots of source downloads plus a JSON manifest."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .errors import FetchError

MANIFEST_VERSION = 1
FRESH_FOR = timedelta(hours=24)


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

    @property
    def id(self) -> str:
        return self.sha256[:12]

    def is_fresh(self, now: datetime | None = None) -> bool:
        checked = datetime.fromisoformat(self.checked_at)
        return (now or now_utc()) - checked < FRESH_FOR


class Cache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or cache_dir()

    @property
    def manifest_path(self) -> Path:
        return self.root / 'manifest.json'

    def snapshot_path(self, sha256: str) -> Path:
        return self.root / 'snapshots' / f'{sha256}.xls'

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
        path = self.snapshot_path(snapshot.sha256)
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
        path = self.snapshot_path(snapshot.sha256)
        if not path.exists():
            _atomic_write(path, content)
        data = self._read()
        entry = data['questions'].setdefault(snapshot.question_id, {'snapshots': []})
        entry['snapshots'] = [s for s in entry['snapshots'] if s['sha256'] != snapshot.sha256]
        entry['snapshots'].append(asdict(snapshot))
        entry['latest'] = snapshot.sha256
        self._write(data)
        return snapshot

    @staticmethod
    def digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()
