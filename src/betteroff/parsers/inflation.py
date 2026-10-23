"""Parser for Michigan's inflation / price expectation table downloads (Tables 32 and 33).

Layout, verified October 2026:
Header row starts with "Date of Survey", followed by:
Down, Same, 1-2, 3-4, 5, 6-9, 10-14, 15+, DK Up, DK,NA, Total,
Median, 25th, 75th, Rng, Mean, Variance, Cases.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from ..errors import ValidationError
from .historical import MONTHS, Grid, ParsedTable, _find_header, _norm, read_grid

if TYPE_CHECKING:
    from ..catalog import Question

PARSER_VERSION = '1'

INFLATION_COLUMNS = {
    'down': 'down',
    'same': 'same',
    '1-2': 'up_1_to_2',
    '3-4': 'up_3_to_4',
    '5': 'up_5',
    '6-9': 'up_6_to_9',
    '10-14': 'up_10_to_14',
    '15+': 'up_15_plus',
    'dk up': 'dk_up',
    'dk,na': 'dk_na',
    'total': 'total',
    'median': 'median',
    '25th': 'p25',
    '75th': 'p75',
    'rng': 'rng',
    'mean': 'mean',
    'variance': 'variance',
    'cases': 'cases',
}

SUMMARY_COLUMNS = ['median', 'mean', 'p25', 'p75', 'rng', 'variance']


def _number(value: object, row: int, col_label: str) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        return math.nan
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip('%').replace(',', '')
    if not text or text.upper() == 'NA':
        return math.nan
    try:
        return float(text)
    except ValueError:
        raise ValidationError(
            f'Unexpected value {value!r} in column "{col_label}" at source row {row + 1}.',
            'The source may use a new code for this table; please report an issue.',
        ) from None


def _wording(grid: Grid, hdr: int) -> tuple[str | None, list[str]]:
    lines = []
    for row in grid[:hdr]:
        cells = [str(v).strip() for v in row if isinstance(v, str) and str(v).strip()]
        if len(cells) == 1:
            lines.append(cells[0])
    notes = [ln.strip('() ').strip() for ln in lines if ln.startswith('(')]
    text = ' '.join(ln for ln in lines if not ln.startswith('('))
    text = re.sub(r'\s+', ' ', text)
    match = re.search(r'the questions? (?:was|were):\s*(.*)', text, re.I)
    if not match:
        return None, notes
    return match.group(1).strip().strip('"\u201c\u201d').strip(), notes


def parse_grid(grid: Grid, question: Question) -> ParsedTable:
    hdr = _find_header(grid)
    header = grid[hdr]

    columns: dict[int, str] = {}
    for col in range(2, len(header)):
        norm_label = _norm(header[col])
        if norm_label in INFLATION_COLUMNS:
            columns[col] = INFLATION_COLUMNS[norm_label]

    missing = [c for c in INFLATION_COLUMNS.values() if c not in columns.values()]
    if missing:
        found = ', '.join(f'"{c}"' for c in header if str(c).strip())
        raise ValidationError(
            f'Table {question.table} headers changed. Found {found}; missing {missing}.',
            'The source layout may have changed; please report an issue.',
        )

    records = []
    seen: dict[date, int] = {}
    for i in range(hdr + 1, len(grid)):
        row = grid[i]
        if all(not str(v).strip() for v in row):
            continue
        month_text = str(row[0]).strip()
        year = row[1] if len(row) > 1 else ''
        month = MONTHS.get(month_text[:3].lower())
        if month is None or not isinstance(year, (int, float)):
            continue
        when = date(int(year), month, 1)
        if when in seen:
            raise ValidationError(
                f'Table {question.table} lists {when:%B %Y} twice (source rows '
                f'{seen[when] + 1} and {i + 1}).',
                'Please report an issue; the parser will not guess which row is correct.',
            )
        seen[when] = i
        record: dict[str, object] = {'date': when}
        for col, key in columns.items():
            record[key] = _number(row[col] if col < len(row) else '', i, key)
        records.append(record)

    if not records:
        raise ValidationError(
            f'Table {question.table} contained no observations.',
            'The download may be incomplete; try again with --refresh.',
        )

    bracket_order = [r.id for r in question.responses]
    order = ['date', *bracket_order, 'total', *SUMMARY_COLUMNS, 'cases']
    frame = pd.DataFrame.from_records(records)[order]
    frame['date'] = pd.to_datetime(frame['date'])
    frame = frame.sort_values('date', ignore_index=True)
    wording, source_notes = _wording(grid, hdr)
    return ParsedTable(frame=frame, wording=wording, source_notes=source_notes)


def parse(content: bytes, question: Question) -> ParsedTable:
    return parse_grid(read_grid(content), question)
