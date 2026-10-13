"""Orchestration shared by the CLI, Python API and recipes."""

from __future__ import annotations

import logging
import warnings
from dataclasses import replace
from datetime import date
from typing import Any

import pandas as pd

from . import __version__
from .cache import Cache, Snapshot, now_utc
from .catalog import Question, load_catalog
from .errors import FetchError, InputError
from .models import Dataset, check_measure, parse_date
from .parsers import historical

log = logging.getLogger('betteroff')
METADATA_SCHEMA_VERSION = 1


class BetteroffWarning(UserWarning):
    """A condition that changes what the returned data means."""


def search(text: str) -> list[Question]:
    return load_catalog().search(text)


def list_questions() -> list[Question]:
    return list(load_catalog().questions)


def describe(identifier: str) -> Question:
    return load_catalog().resolve(identifier)


def _period(ts: pd.Timestamp) -> str:
    return f'{ts:%Y-%m}'


def compare_snapshots(old: pd.DataFrame, new: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    """Describe appended, removed and revised months between two parsed frames."""
    o = old.set_index('date')[columns]
    n = new.set_index('date')[columns]
    appended = n.index.difference(o.index)
    removed = o.index.difference(n.index)
    common = n.index.intersection(o.index)
    a, b = o.loc[common], n.loc[common]
    differs = ~((a == b) | (a.isna() & b.isna()))
    changed = differs.any(axis=1)
    return {
        'appended_months': [_period(d) for d in appended],
        'removed_months': [_period(d) for d in removed],
        'changed_months': [_period(d) for d in changed[changed].index],
        'changed_values': int(differs.to_numpy().sum()),
    }


def _parse_and_validate(content: bytes, question: Question) -> tuple[Any, list[dict]]:
    from .validate import validate

    parsed = historical.parse(content, question)
    flags = validate(parsed, question)
    return parsed, flags


def _fetch(question: Question, client: Any = None) -> Any:
    from .fetch import download_table

    return download_table(question.table, load_catalog().landing_url, client=client)


def load(
    question: Question,
    *,
    refresh: bool = False,
    offline: bool = False,
    cache: Cache | None = None,
    client: Any = None,
) -> tuple[Any, list[dict], Snapshot, str, dict[str, Any] | None]:
    """Return parsed data, flags, snapshot, retrieval mode and revisions."""
    if refresh and offline:
        raise InputError('--refresh and --offline cannot be used together.', 'Choose one.')
    cache = cache or Cache()
    current = cache.latest(question.id)

    if offline:
        if current is None:
            raise FetchError(
                f'No saved snapshot for {question.id}.',
                f'Run `betteroff get {question.id}` once while online.',
            )
        parsed, flags = _parse_and_validate(cache.read_bytes(current), question)
        warnings.warn(
            f'Offline: using {question.id} snapshot {current.id} retrieved '
            f'{current.retrieved_at}; latest month {current.latest_period}.',
            BetteroffWarning,
            stacklevel=3,
        )
        return parsed, flags, current, 'offline', None

    if current is not None and not refresh and current.is_fresh():
        parsed, flags = _parse_and_validate(cache.read_bytes(current), question)
        return parsed, flags, current, 'cached', None

    log.info('Checking source for table %s (%s)...', question.table, question.id)
    try:
        download = _fetch(question, client)
    except FetchError:
        if refresh or current is None:
            raise
        parsed, flags = _parse_and_validate(cache.read_bytes(current), question)
        warnings.warn(
            f'Could not reach the source; using {question.id} snapshot {current.id} '
            f'last checked {current.checked_at}. Use --refresh to require fresh data.',
            BetteroffWarning,
            stacklevel=3,
        )
        return parsed, flags, current, 'stale', None

    parsed, flags = _parse_and_validate(download.content, question)
    sha = Cache.digest(download.content)
    stamp = now_utc().isoformat()
    frame = parsed.frame
    snapshot = Snapshot(
        sha256=sha,
        question_id=question.id,
        table=question.table,
        url=download.url,
        source_period=download.source_period,
        retrieved_at=stamp,
        checked_at=stamp,
        first_period=_period(frame['date'].min()),
        latest_period=_period(frame['date'].max()),
        observations=len(frame),
        parser_version=historical.PARSER_VERSION,
    )
    revisions = None
    if current is not None and current.sha256 == sha:
        snapshot = replace(snapshot, retrieved_at=current.retrieved_at)
        log.info(
            'No change since %s; latest month %s.', current.retrieved_at, snapshot.latest_period
        )
    elif current is not None:
        try:
            old, _ = _parse_and_validate(cache.read_bytes(current), question)
        except Exception:  # an unreadable old snapshot shouldn't block a good new one
            old = None
        if old is not None:
            columns = [*(r.id for r in question.responses), 'index']
            revisions = compare_snapshots(old.frame, frame, columns)
            revisions['previous_snapshot'] = current.id
            _report_revisions(question, revisions)
    cache.store(snapshot, download.content)
    return parsed, flags, snapshot, 'fresh', revisions


def _report_revisions(question: Question, rev: dict[str, Any]) -> None:
    if rev['appended_months']:
        log.info(
            '%s: %d new month(s) through %s.',
            question.id,
            len(rev['appended_months']),
            rev['appended_months'][-1],
        )
    else:
        log.info('%s: no new months.', question.id)
    if rev['changed_months'] or rev['removed_months']:
        months = rev['changed_months'] + rev['removed_months']
        shown = ', '.join(months[:6]) + (' ...' if len(months) > 6 else '')
        warnings.warn(
            f'{question.id}: source revised {len(rev["changed_months"])} month(s) and removed '
            f'{len(rev["removed_months"])} since snapshot {rev["previous_snapshot"]} ({shown}).',
            BetteroffWarning,
            stacklevel=4,
        )


def build_metadata(
    question: Question,
    parsed: Any,
    flags: list[dict],
    snapshot: Snapshot,
    mode: str,
    revisions: dict[str, Any] | None,
) -> dict[str, Any]:
    catalog = load_catalog()
    quirks = [f for f in flags if f['check'] != 'wording_changed']
    if quirks and mode == 'fresh':
        log.info(
            '%s: %d source quirk(s) flagged in metadata (quality_flags).', question.id, len(quirks)
        )
    for f in flags:
        if f['check'] == 'wording_changed':
            warnings.warn(
                f'{question.id}: the question wording in the source file no longer matches the '
                f'catalog. {f["detail"]}',
                BetteroffWarning,
                stacklevel=4,
            )
    return {
        'schema_version': METADATA_SCHEMA_VERSION,
        'betteroff_version': __version__,
        'parser_version': historical.PARSER_VERSION,
        'question': {
            **question.to_dict(),
            'index': {'label': catalog.index_label, 'definition': catalog.index_definition},
        },
        'population': catalog.population,
        'units': {'share': 'percent', 'index': 'index'},
        'source': {
            'publisher': catalog.attribution,
            'landing_url': catalog.landing_url,
            'download_url': snapshot.url,
            'table': question.table,
            'source_period': snapshot.source_period,
            'release_status': 'unknown',
            'usage_agreement': catalog.agreement_url,
        },
        'snapshot': {
            'id': snapshot.id,
            'sha256': snapshot.sha256,
            'retrieved_at': snapshot.retrieved_at,
            'checked_at': snapshot.checked_at,
            'mode': mode,
        },
        'coverage': {
            'first_period': snapshot.first_period,
            'latest_period': snapshot.latest_period,
            'observations': snapshot.observations,
            'monthly_since': (question.monthly_since or catalog.monthly_since).isoformat()[:7],
        },
        'notes': [*catalog.notes, *question.notes],
        'source_notes': parsed.source_notes,
        'quality_flags': flags,
        'revisions': revisions,
    }


def get(
    identifier: str,
    *,
    refresh: bool = False,
    offline: bool = False,
    start: str | date | None = None,
    end: str | date | None = None,
    measure: str = 'share',
    cache: Cache | None = None,
    client: Any = None,
) -> Dataset:
    """Fetch (or reuse a cached copy of) a table, validate it and return a Dataset."""
    question = load_catalog().resolve(identifier)
    check_measure(measure)
    start_d, end_d = parse_date(start, 'start'), parse_date(end, 'end')
    parsed, flags, snapshot, mode, revisions = load(
        question, refresh=refresh, offline=offline, cache=cache, client=client
    )
    metadata = build_metadata(question, parsed, flags, snapshot, mode, revisions)
    return Dataset(
        question=question,
        frame=parsed.frame,
        metadata=metadata,
        measure=measure,
        start=start_d,
        end=end_d,
    )


def cached_dataset(question: Question, cache: Cache | None = None) -> Dataset | None:
    """Dataset from the latest snapshot without touching the network, or None."""
    cache = cache or Cache()
    snapshot = cache.latest(question.id)
    if snapshot is None:
        return None
    parsed, flags = _parse_and_validate(cache.read_bytes(snapshot), question)
    metadata = build_metadata(question, parsed, flags, snapshot, 'cached', None)
    return Dataset(question=question, frame=parsed.frame, metadata=metadata)
