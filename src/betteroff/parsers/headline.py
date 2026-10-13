"""Parser for the headline index CSV files on Michigan's main site.

Layout, verified October 2026. The history file (tbmics.csv, tbmiccice.csv)
has a header row "Month,YYYY," then one column per index, and one row per final
reading. The current file (tbcics.csv, tbciccice.csv) has a title, a header row
starting "DATE OF SURVEY", the last 12 months and, while one is out, this
month's preliminary reading with "(P)" after the month name.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import date

import pandas as pd

from ..cache import unbundle
from ..catalog import Question
from ..errors import ValidationError
from .historical import MONTHS, ParsedTable

PARSER_VERSION = '1'
ROW = re.compile(r'^([A-Za-z]+)\s*(\(P\))?$')


def _norm(text: object) -> str:
    return re.sub(r'\s+', ' ', str(text)).strip().casefold()


def _fail(question: Question, detail: str) -> ValidationError:
    return ValidationError(
        f'{question.title} ({question.table}): {detail}.',
        'The source layout may have changed; please report an issue.',
    )


def _rows(text: str) -> list[list[str]]:
    return [[c.strip() for c in row] for row in csv.reader(text.splitlines())]


def _column(header: list[str], name: str, question: Question, which: str) -> int:
    for i, label in enumerate(header):
        if _norm(label) == _norm(name):
            return i
    found = ', '.join(f'"{h}"' for h in header if h)
    raise _fail(question, f'the {which} file has no "{name}" column (found {found})')


def _value(text: str, question: Question, where: str) -> float:
    if not text or text.upper() == 'NA':
        return math.nan
    try:
        return float(text.replace(',', ''))
    except ValueError:
        raise _fail(question, f'unexpected value "{text}" in {where}') from None


def _date(month_text: str, year_text: str) -> tuple[date, bool] | None:
    match = ROW.match(month_text)
    month = MONTHS.get(match.group(1)[:3].lower()) if match else None
    if match is None or month is None or not re.fullmatch(r'\d{4}(\.0)?', year_text):
        return None
    return date(int(float(year_text)), month, 1), bool(match.group(2))


def parse_history(text: str, question: Question) -> dict[date, float]:
    assert question.source is not None
    rows = _rows(text)
    if not rows or [_norm(c) for c in rows[0][:2]] != ['month', 'yyyy']:
        raise _fail(question, 'the history file no longer starts with "Month,YYYY"')
    col = _column(rows[0], question.source.history_column, question, 'history')
    out: dict[date, float] = {}
    for n, row in enumerate(rows[1:], start=2):
        if not any(row):
            continue
        parsed = _date(row[0], row[1] if len(row) > 1 else '')
        if parsed is None or parsed[1]:
            raise _fail(question, f'could not read the date in history row {n}: {row[:3]}')
        when = parsed[0]
        if when in out:
            raise _fail(question, f'the history file lists {when:%B %Y} twice')
        value = _value(row[col] if col < len(row) else '', question, f'history row {n}')
        if not math.isnan(value):  # Blank before an index began
            out[when] = value
    return out


def parse_current(text: str, question: Question) -> list[tuple[date, float, bool]]:
    assert question.source is not None
    rows = _rows(text)
    hdr = next((i for i, r in enumerate(rows) if r and _norm(r[0]) == 'date of survey'), None)
    if hdr is None:
        raise _fail(question, 'the current file has no "DATE OF SURVEY" header row')
    col = _column(rows[hdr], question.source.current_column, question, 'current')
    out = []
    for n, row in enumerate(rows[hdr + 1 :], start=hdr + 2):
        if not any(row):
            continue
        parsed = _date(row[0], row[1] if len(row) > 1 else '')
        if parsed is None:
            raise _fail(question, f'could not read the date in current-file row {n}: {row[:3]}')
        value = _value(row[col] if col < len(row) else '', question, f'current-file row {n}')
        if not math.isnan(value):
            out.append((parsed[0], value, parsed[1]))
    return out


def parse(content: bytes, question: Question) -> ParsedTable:
    """Join final history with newer final and preliminary readings from the current file."""
    assert question.source is not None
    try:
        files = unbundle(content)
        history_text = files[question.source.history_url]
        current_text = files[question.source.current_url]
    except (ValueError, KeyError) as exc:
        raise _fail(question, f'the saved snapshot is not a complete bundle ({exc})') from None

    finals = parse_history(history_text, question)
    preliminary: dict[date, float] = {}
    flags: list[dict] = []
    for when, value, is_prelim in parse_current(current_text, question):
        if when in finals:
            # The history file is updated at the final release; trust it.
            if not is_prelim and finals[when] != value:
                flags.append(
                    {
                        'date': when.isoformat(),
                        'check': 'current_file_differs',
                        'detail': f'history {finals[when]}, current file {value}',
                    }
                )
        elif is_prelim:
            preliminary[when] = value
        else:
            finals[when] = value

    if not finals:
        raise _fail(question, 'the history file contained no readings')
    if len(preliminary) > 1:
        months = ', '.join(f'{d:%B %Y}' for d in sorted(preliminary))
        raise _fail(question, f'more than one preliminary reading ({months})')
    if preliminary and min(preliminary) <= max(finals):
        raise _fail(question, 'a preliminary reading is older than the latest final reading')

    records = [{'date': d, 'index': v, 'preliminary': False} for d, v in finals.items()]
    records += [{'date': d, 'index': v, 'preliminary': True} for d, v in preliminary.items()]
    frame = pd.DataFrame.from_records(records)
    frame['date'] = pd.to_datetime(frame['date'])
    frame = frame.sort_values('date', ignore_index=True)
    return ParsedTable(frame=frame, wording=None, flags=flags)
