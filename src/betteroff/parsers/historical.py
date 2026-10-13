"""Parser for Michigan's historical ("RB") table downloads.

Layout, verified October 2026: question wording in the rows above a header row
that starts with "Date of Survey"; then month name, year, one column per
response, Total, Relative (the index score) and Cases.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ..catalog import Question
from ..errors import ValidationError

PARSER_VERSION = '1'
MONTHS = {
    m: i
    for i, m in enumerate(
        ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'],
        start=1,
    )
}
EXTRA_COLUMNS = {'total': 'total', 'relative': 'index', 'cases': 'cases'}

Grid = list[list[object]]


@dataclass
class ParsedTable:
    # Columns: date, one per response id in catalog order, total, index, cases
    frame: pd.DataFrame
    wording: str | None
    source_notes: list[str] = field(default_factory=list)


def _norm(text: object) -> str:
    return re.sub(r'\s+', ' ', str(text)).strip().casefold()


def read_grid(content: bytes) -> Grid:
    import xlrd

    try:
        book = xlrd.open_workbook(file_contents=content)
    except Exception as exc:
        raise ValidationError(
            f'Could not read the downloaded Excel file ({exc}).',
            'The source format may have changed; please report an issue.',
        ) from exc
    sheet = book.sheet_by_index(0)
    return [sheet.row_values(r) for r in range(sheet.nrows)]


def _find_header(grid: Grid) -> int:
    for i, row in enumerate(grid[:60]):
        if row and re.sub(r'\s+', '', str(row[0])).lower().startswith('dateofsurvey'):
            return i
    raise ValidationError(
        'Could not find the "Date of Survey" header row in the source file.',
        'The source layout may have changed; please report an issue.',
    )


def _column_labels(grid: Grid, hdr: int) -> dict[int, str]:
    header = grid[hdr]
    above = grid[hdr - 1] if hdr > 0 else []
    # Some tables split labels over two rows ("Income" above "Up More").
    stacked = any(str(v).strip() for v in above) and all(
        not str(v).strip() or (i >= 2 and len(str(v).strip()) < 25) for i, v in enumerate(above)
    )
    labels = {}
    for col in range(2, len(header)):
        parts = [str(header[col]).strip()]
        if stacked and col < len(above) and str(above[col]).strip():
            parts.insert(0, str(above[col]).strip())
        label = ' '.join(p for p in parts if p)
        if label:
            labels[col] = re.sub(r'\s+', ' ', label)
    return labels


def _wording(grid: Grid, hdr: int) -> tuple[str | None, list[str]]:
    lines = []
    for row in grid[:hdr]:
        cells = [str(v).strip() for v in row if isinstance(v, str) and v.strip()]
        if len(cells) == 1:  # Multi-cell rows are stacked column labels
            lines.append(cells[0])
    notes = [ln.strip('() ').strip() for ln in lines if ln.startswith('(')]
    text = ' '.join(ln for ln in lines if not ln.startswith('('))
    text = re.sub(r'\s+', ' ', text)
    match = re.search(r'the question was:\s*(.*)', text, re.I)
    if not match:
        return None, notes
    return match.group(1).strip().strip('"\u201c\u201d').strip(), notes


def _number(value: object, row: int, col_label: str) -> float:
    if value is None or (isinstance(value, str) and not value.strip()):
        return math.nan
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().rstrip('%').replace(',', '')
    try:
        return float(text)
    except ValueError:
        raise ValidationError(
            f'Unexpected value {value!r} in column "{col_label}" at source row {row + 1}.',
            'The source may use a new code for this table; please report an issue.',
        ) from None


def parse_grid(grid: Grid, question: Question) -> ParsedTable:
    hdr = _find_header(grid)
    labels = _column_labels(grid, hdr)
    expected = {_norm(r.source_label): r.id for r in question.responses}
    expected.update(EXTRA_COLUMNS)

    columns: dict[int, str] = {}
    unexpected = []
    for col, label in labels.items():
        key = expected.get(_norm(label))
        if key is None or key in columns.values():
            unexpected.append(label)
        else:
            columns[col] = key
    missing = [k for k in expected.values() if k not in columns.values()]
    if unexpected or missing:
        found = ', '.join(f'"{lab}"' for lab in labels.values())
        raise ValidationError(
            f'Table {question.table} headers changed. Found {found}; '
            f'unexpected {unexpected or "none"}, missing {missing or "none"}.',
            'The catalog response mapping needs review before this table can be used; '
            'please report an issue.',
        )

    records = []
    notes: list[str] = []
    seen: dict[date, int] = {}
    for i in range(hdr + 1, len(grid)):
        row = grid[i]
        if all(not str(v).strip() for v in row):
            continue
        month_text = str(row[0]).strip()
        year = row[1] if len(row) > 1 else ''
        month = MONTHS.get(month_text[:3].lower())
        if month is None or not isinstance(year, int | float):
            values = [str(v).strip() for v in row if str(v).strip()]
            if all(not re.fullmatch(r'-?[\d.]+%?', v) for v in values):
                notes.append(' '.join(values))
                continue
            raise ValidationError(
                f'Could not read the date in source row {i + 1}: {values[:4]}.',
                'The source layout may have changed; please report an issue.',
            )
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
            record[key] = _number(row[col] if col < len(row) else '', i, labels[col])
        records.append(record)

    if not records:
        raise ValidationError(
            f'Table {question.table} contained no observations.',
            'The download may be incomplete; try again with --refresh.',
        )
    order = ['date', *(r.id for r in question.responses), 'total', 'index', 'cases']
    frame = pd.DataFrame.from_records(records)[order]
    frame['date'] = pd.to_datetime(frame['date'])
    frame = frame.sort_values('date', ignore_index=True)
    wording, source_notes = _wording(grid, hdr)
    return ParsedTable(frame=frame, wording=wording, source_notes=source_notes + notes)


def parse(content: bytes, question: Question) -> ParsedTable:
    return parse_grid(read_grid(content), question)
