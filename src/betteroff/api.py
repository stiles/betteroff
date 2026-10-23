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
from .parsers import headline, historical, inflation

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
    """Describe appended, removed and revised months between two parsed frames.

    For headline indexes, a month that was preliminary and is now final counts as
    finalized, not revised, whether or not its value changed.
    """
    o = old.set_index('date')
    n = new.set_index('date')
    appended = n.index.difference(o.index)
    removed = o.index.difference(n.index)
    common = n.index.intersection(o.index)
    a, b = o.loc[common, columns], n.loc[common, columns]
    differs = ~((a == b) | (a.isna() & b.isna()))
    out: dict[str, Any] = {}
    if 'preliminary' in o and 'preliminary' in n:
        was_prelim = o.loc[common, 'preliminary'].astype(bool)
        now_final = ~n.loc[common, 'preliminary'].astype(bool)
        finalized = was_prelim & now_final
        before = o.loc[common, 'index'].astype('float64').to_dict()
        after = n.loc[common, 'index'].astype('float64').to_dict()
        out['finalized'] = [
            {'month': _period(d), 'preliminary': before[d], 'final': after[d]}
            for d in finalized[finalized].index
        ]
        differs = differs.loc[~finalized]
    changed = differs.any(axis=1)
    return {
        'appended_months': [_period(d) for d in appended],
        'removed_months': [_period(d) for d in removed],
        'changed_months': [_period(d) for d in changed[changed].index],
        'changed_values': int(differs.to_numpy().sum()),
        **out,
    }


def _parser(question: Question) -> Any:
    if question.is_index:
        return headline
    if question.is_inflation:
        return inflation
    return historical


def _parse_and_validate(content: bytes, question: Question) -> tuple[Any, list[dict]]:
    from .validate import validate

    parsed = _parser(question).parse(content, question)
    flags = validate(parsed, question)
    return parsed, flags


def _fetch(question: Question, client: Any = None) -> Any:
    from .fetch import download_index, download_table

    catalog = load_catalog()
    if question.source is not None:
        urls = [question.source.history_url, question.source.current_url]
        return download_index(urls, catalog.headline.page_url, client=client)
    return download_table(question.table, catalog.landing_url, client=client)


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

    what = question.table if question.is_index else f'table {question.table}'
    log.info('Checking source for %s (%s)...', what, question.id)
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
        parser_version=_parser(question).PARSER_VERSION,
        suffix='.json' if question.is_index else '.xls',
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
            if question.is_inflation:
                columns = ['median', 'mean', *(r.id for r in question.responses)]
            else:
                columns = [*(r.id for r in question.responses), 'index']
            revisions = compare_snapshots(old.frame, frame, columns)
            revisions['previous_snapshot'] = current.id
            _report_revisions(question, revisions)
    cache.store(snapshot, download.content)
    return parsed, flags, snapshot, 'fresh', revisions


def _report_revisions(question: Question, rev: dict[str, Any]) -> None:
    for f in rev.get('finalized', []):
        log.info(
            '%s: %s is now final at %s (preliminary was %s).',
            question.id,
            f['month'],
            f['final'],
            f['preliminary'],
        )
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
    coverage: dict[str, Any] = {
        'first_period': snapshot.first_period,
        'latest_period': snapshot.latest_period,
        'observations': snapshot.observations,
        'monthly_since': (question.monthly_since or catalog.monthly_since).isoformat()[:7],
    }
    if question.source is not None:
        latest_prelim = bool(parsed.frame['preliminary'].iloc[-1])
        coverage['latest_preliminary'] = latest_prelim
        question_meta = {**question.to_dict(), 'base': catalog.headline.base}
        units = {'index': 'index'}
        source: dict[str, Any] = {
            'publisher': catalog.attribution,
            'landing_url': catalog.headline.page_url,
            'download_urls': [question.source.history_url, question.source.current_url],
            'code': question.table,
            'release_status': 'preliminary' if latest_prelim else 'final',
            'usage_agreement': catalog.agreement_url,
        }
    elif question.is_inflation:
        question_meta = question.to_dict()
        units = {'median': 'percent', 'mean': 'percent', 'summary': 'percent', 'share': 'percent'}
        source = {
            'publisher': catalog.attribution,
            'landing_url': catalog.landing_url,
            'download_url': snapshot.url,
            'table': question.table,
            'source_period': snapshot.source_period,
            'release_status': 'unknown',
            'usage_agreement': catalog.agreement_url,
        }
    else:
        question_meta = {
            **question.to_dict(),
            'index': {'label': catalog.index_label, 'definition': catalog.index_definition},
        }
        units = {'share': 'percent', 'index': 'index'}
        source = {
            'publisher': catalog.attribution,
            'landing_url': catalog.landing_url,
            'download_url': snapshot.url,
            'table': question.table,
            'source_period': snapshot.source_period,
            'release_status': 'unknown',
            'usage_agreement': catalog.agreement_url,
        }
    return {
        'schema_version': METADATA_SCHEMA_VERSION,
        'betteroff_version': __version__,
        'parser_version': _parser(question).PARSER_VERSION,
        'question': question_meta,
        'population': catalog.population,
        'units': units,
        'source': source,
        'snapshot': {
            'id': snapshot.id,
            'sha256': snapshot.sha256,
            'retrieved_at': snapshot.retrieved_at,
            'checked_at': snapshot.checked_at,
            'mode': mode,
        },
        'coverage': coverage,
        'notes': catalog.notes_for(question),
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
    measure: str | None = None,
    cache: Cache | None = None,
    client: Any = None,
) -> Dataset:
    """Fetch (or reuse a cached copy of) a table or index, validate it and return a Dataset.

    `measure` defaults to `share` for tables and `index` for headline indexes.
    """
    question = load_catalog().resolve(identifier)
    measure = check_measure(measure, question)
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
