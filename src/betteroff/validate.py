"""Checks on parsed tables. Structural problems raise; known source quirks become flags."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from .catalog import Question
from .errors import ValidationError
from .parsers.historical import ParsedTable

SUM_TOLERANCE = 1.0  # Source shares are rounded to whole percents
INDEX_TOLERANCE = 1.0
MAX_FLAGS_PER_CHECK = 25


def _alnum(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', text.lower())


def _fail(question: Question, detail: str) -> ValidationError:
    name = question.title if question.is_index else f'Table {question.table}'
    return ValidationError(
        f'{name} failed validation: {detail}.',
        'The source may have changed; please report an issue. Your cached data was not replaced.',
    )


def validate_index(
    parsed: ParsedTable, question: Question, today: date | None = None
) -> list[dict]:
    """Checks for a headline index. Raises on impossible data; returns the parser's flags."""
    frame = parsed.frame
    today = today or date.today()
    if frame['date'].duplicated().any():
        raise _fail(question, 'duplicate months')
    latest = frame['date'].max().date()
    if latest > today.replace(day=1):
        raise _fail(question, f'latest month {latest:%B %Y} is in the future')
    if ((frame['index'] <= 0) | (frame['index'] > 200)).any():
        raise _fail(question, 'an index value is outside 0-200')
    if frame['preliminary'].sum() > 1 or (
        frame['preliminary'].any() and not frame['preliminary'].iloc[-1]
    ):
        raise _fail(question, 'only the latest month can be preliminary')
    return list(parsed.flags)


def validate(parsed: ParsedTable, question: Question, today: date | None = None) -> list[dict]:
    """Raise on impossible data; return a list of flags for suspicious rows."""
    if question.is_index:
        return validate_index(parsed, question, today)
    frame = parsed.frame
    ids = [r.id for r in question.responses]
    shares = frame[ids]
    today = today or date.today()

    if frame['date'].duplicated().any():
        raise _fail(question, 'duplicate months')
    latest = frame['date'].max().date()
    if latest > today.replace(day=1):
        raise _fail(question, f'latest month {latest:%B %Y} is in the future')
    for rid in ids:
        if shares[rid].isna().all():
            raise _fail(question, f'response "{rid}" has no values')
    if ((shares < 0) | (shares > 100)).any().any():
        raise _fail(question, 'a response share is outside 0-100')
    if ((frame['index'] < 0) | (frame['index'] > 200)).any():
        raise _fail(question, 'an index score is outside 0-200')
    if (frame['cases'] <= 0).any():
        raise _fail(question, 'a case count is zero or negative')

    flags: list[dict] = []

    def flag(mask: pd.Series, check: str, detail: pd.Series) -> None:
        for idx in frame.index[mask.fillna(False).astype(bool)][:MAX_FLAGS_PER_CHECK]:
            flags.append(
                {
                    'date': f'{frame.at[idx, "date"]:%Y-%m-%d}',
                    'check': check,
                    'detail': str(detail.at[idx]),
                }
            )

    total_off = (frame['total'] - 100).abs() > 0.5
    flag(total_off, 'total_not_100', 'total ' + frame['total'].astype(str))

    complete = shares.notna().all(axis=1)
    diff = shares.sum(axis=1) - frame['total']
    flag(
        complete & (diff.abs() > SUM_TOLERANCE),
        'shares_do_not_sum_to_total',
        'difference ' + diff.round(1).astype(str),
    )

    pos = [r.id for r in question.responses if r.polarity == 'positive']
    neg = [r.id for r in question.responses if r.polarity == 'negative']
    computed = frame[pos].sum(axis=1, min_count=1) - frame[neg].sum(axis=1, min_count=1) + 100
    idiff = frame['index'] - computed
    flag(
        idiff.abs() > INDEX_TOLERANCE,
        'index_does_not_match_shares',
        'difference ' + idiff.round(1).astype(str),
    )

    if parsed.wording and _alnum(parsed.wording) != _alnum(question.wording):
        flags.append(
            {
                'date': None,
                'check': 'wording_changed',
                'detail': f'Source wording now reads: {parsed.wording}',
            }
        )
    return flags
