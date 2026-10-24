"""Parser for Michigan's index breakdown tables (2n, 3n, 4n, 5a and 5b).

Layout, verified October 2026 against the historical ("RB") downloads: a banner
row naming the grouping, such as "RESPONDENT POLITICAL PARTY"; a row with
SENTIMENT INDEX, CURRENT INDEX and EXPECTED INDEX over their blocks; then group
labels, split over two rows in some tables, ending in the "Date of Survey" row.
Every block has one column per group, in the same order. There is no Total,
Relative or Cases column and no question wording.
"""

from __future__ import annotations

import pandas as pd

from ..catalog import Question
from ..errors import ValidationError
from .historical import Grid, ParsedTable, _find_header, _norm, read_grid, read_rows

PARSER_VERSION = '1'
FIRST_COLUMN = 2  # Columns 0 and 1 hold the month and year


def _fail(question: Question, detail: str) -> ValidationError:
    return ValidationError(
        f'Table {question.table} layout changed: {detail}.',
        'The catalog mapping needs review before this table can be used; please report an issue.',
    )


def _cells(row: list[object]) -> dict[str, int]:
    return {_norm(v): c for c, v in enumerate(row) if str(v).strip()}


def parse_grid(grid: Grid, question: Question) -> ParsedTable:
    b = question.breakdown
    assert b is not None
    hdr = _find_header(grid)
    wanted = [_norm(label) for label in b.blocks]

    block_row = next(
        (i for i in range(hdr, -1, -1) if all(w in _cells(grid[i]) for w in wanted)), None
    )
    if block_row is None:
        raise _fail(question, f'no row lists {", ".join(b.blocks)}')
    banners = [str(v).strip() for row in grid[:block_row] for v in row if str(v).strip()]
    if _norm(b.banner) not in {_norm(v) for v in banners}:
        found = ', '.join(f'"{v}"' for v in banners) or 'nothing'
        raise _fail(question, f'expected the banner "{b.banner}" above the indexes, found {found}')

    n = len(question.responses)
    label_rows = grid[block_row + 1 : hdr + 1]
    width = max(len(r) for r in label_rows)
    found_labels: dict[int, str] = {}
    for col in range(FIRST_COLUMN, width):
        parts = [str(r[col]).strip() for r in label_rows if col < len(r) and str(r[col]).strip()]
        if parts:
            found_labels[col] = ' '.join(' '.join(parts).split())
    expected = {
        FIRST_COLUMN + k * n + j: r.source_label
        for k in range(len(b.blocks))
        for j, r in enumerate(question.responses)
    }
    if {c: _norm(v) for c, v in found_labels.items()} != {c: _norm(v) for c, v in expected.items()}:
        found = ', '.join(f'"{v}"' for v in found_labels.values())
        want = ', '.join(f'"{r.source_label}"' for r in question.responses)
        raise _fail(
            question,
            f'expected {want} under each of {len(b.blocks)} indexes, found {found}',
        )

    cells = _cells(grid[block_row])
    for k, label in enumerate(b.blocks):
        lo = FIRST_COLUMN + k * n
        if not lo <= cells[_norm(label)] < lo + n:
            raise _fail(question, f'"{label}" no longer sits over its block of columns')

    k = b.blocks.index(b.block)
    columns = {FIRST_COLUMN + k * n + j: r.id for j, r in enumerate(question.responses)}
    labels = {c: f'{b.block} {found_labels[c]}' for c in columns}
    records, notes = read_rows(grid, hdr, columns, labels, question.table)
    frame = pd.DataFrame.from_records(records)[['date', *(r.id for r in question.responses)]]
    frame['date'] = pd.to_datetime(frame['date'])
    frame = frame.sort_values('date', ignore_index=True)
    return ParsedTable(frame=frame, wording=None, source_notes=notes)


def parse(content: bytes, question: Question) -> ParsedTable:
    return parse_grid(read_grid(content), question)
