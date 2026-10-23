"""The Dataset returned to Python users and consumed by exports and charts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

import pandas as pd

from .catalog import Question, load_catalog
from .errors import InputError

if TYPE_CHECKING:
    import altair as alt

MEASURES = ('share', 'index', 'median', 'mean', 'summary')
UNITS = {
    'share': 'percent',
    'index': 'index',
    'median': 'percent',
    'mean': 'percent',
    'summary': 'percent',
}


def parse_date(value: str | date | None, name: str = 'date') -> date | None:
    if value is None or isinstance(value, date):
        return value
    text = value.strip()
    try:
        if len(text) == 4:
            return date(int(text), 1, 1)
        if len(text) == 7:
            return date.fromisoformat(f'{text}-01')
        return date.fromisoformat(text).replace(day=1)
    except ValueError:
        raise InputError(
            f'Could not read {name} "{value}".', 'Use YYYY, YYYY-MM or YYYY-MM-DD.'
        ) from None


def check_measure(measure: str | None, question: Question | None = None) -> str:
    """Validate a measure, defaulting by kind.

    Shares for tables, the index for headline indexes, median for inflation.
    """
    if not measure:
        if question is not None:
            if question.is_index:
                return 'index'
            if question.is_inflation:
                return 'median'
        return 'share'
    if measure not in MEASURES:
        raise InputError(f'Unknown measure "{measure}".', f'Use one of: {", ".join(MEASURES)}.')
    if question is not None:
        if question.is_index and measure != 'index':
            raise InputError(
                f'{question.title} is an index; it has no response shares or summary statistics.',
                'Drop --measure, or use --measure index.',
            )
        if question.is_inflation and measure == 'index':
            raise InputError(
                f'{question.title} is an inflation table; it has no index score.',
                'Use --measure median (default), summary or share.',
            )
        if (
            not question.is_inflation
            and not question.is_index
            and measure in ('median', 'mean', 'summary')
        ):
            raise InputError(
                f'{question.title} has no {measure} measure.',
                'Use --measure share (default) or --measure index.',
            )
    return measure


@dataclass
class Dataset:
    """Validated observations for one question plus the metadata that travels with them.

    `frame` holds the full history in source shape (one row per month). `data`
    and `wide()` apply `measure`, `start` and `end`.
    """

    question: Question
    frame: pd.DataFrame
    metadata: dict[str, Any]
    measure: str = ''  # Empty means the default for the kind of series
    start: date | None = None
    end: date | None = None

    def __post_init__(self) -> None:
        self.measure = check_measure(self.measure, self.question)
        if self.start and self.end and self.start > self.end:
            raise InputError('--start is after --end.', 'Swap the dates.')

    def _trim(self, frame: pd.DataFrame) -> pd.DataFrame:
        mask = pd.Series(True, index=frame.index)
        if self.start:
            mask &= frame['date'] >= pd.Timestamp(self.start)
        if self.end:
            mask &= frame['date'] <= pd.Timestamp(self.end)
        return frame.loc[mask].reset_index(drop=True)

    @property
    def value_columns(self) -> list[str]:
        if self.question.is_inflation:
            if self.measure == 'median':
                return ['median']
            if self.measure == 'mean':
                return ['mean']
            if self.measure == 'summary':
                return ['median', 'mean', 'p25', 'p75', 'rng']
            return [r.id for r in self.question.responses]
        if self.measure == 'index':
            return ['index']
        return [r.id for r in self.question.responses]

    @property
    def data(self) -> pd.DataFrame:
        """Tidy observations: one row per month and response, or per month for an index."""
        wide = self._trim(self.frame)
        if self.question.is_index:
            return pd.DataFrame(
                {
                    'date': wide['date'],
                    'question_id': self.question.id,
                    'measure': 'index',
                    'response_id': 'index',
                    'response_label': self.question.title,
                    'value': wide['index'].astype('float64'),
                    'unit': 'index',
                    'preliminary': wide['preliminary'].astype(bool),
                    'population': self.metadata.get('population', 'all_households'),
                }
            )
        if self.question.is_inflation:
            if self.measure in ('median', 'mean'):
                label = 'Median' if self.measure == 'median' else 'Mean'
                return pd.DataFrame(
                    {
                        'date': wide['date'],
                        'question_id': self.question.id,
                        'measure': self.measure,
                        'response_id': self.measure,
                        'response_label': label,
                        'value': wide[self.measure].astype('float64'),
                        'unit': 'percent',
                        'cases': wide['cases'].astype('Int64'),
                        'population': self.metadata.get('population', 'all_households'),
                    }
                )
            if self.measure == 'summary':
                summary_labels = {
                    'median': 'Median',
                    'mean': 'Mean',
                    'p25': '25th percentile',
                    'p75': '75th percentile',
                    'rng': 'Interquartile range',
                }
                tidy = wide.melt(
                    id_vars=['date', 'cases'],
                    value_vars=self.value_columns,
                    var_name='response_id',
                    value_name='value',
                )
                order = {rid: i for i, rid in enumerate(self.value_columns)}
                tidy['_order'] = tidy['response_id'].map(order)
                tidy = tidy.sort_values(['date', '_order'], ignore_index=True)
                return pd.DataFrame(
                    {
                        'date': tidy['date'],
                        'question_id': self.question.id,
                        'measure': 'summary',
                        'response_id': tidy['response_id'],
                        'response_label': tidy['response_id'].map(summary_labels),
                        'value': tidy['value'].astype('float64'),
                        'unit': 'percent',
                        'cases': tidy['cases'].astype('Int64'),
                        'population': self.metadata.get('population', 'all_households'),
                    }
                )
            # measure == 'share'
            labels = {r.id: r.source_label for r in self.question.responses}
            tidy = wide.melt(
                id_vars=['date', 'cases'],
                value_vars=self.value_columns,
                var_name='response_id',
                value_name='value',
            )
            order = {rid: i for i, rid in enumerate(self.value_columns)}
            tidy['_order'] = tidy['response_id'].map(order)
            tidy = tidy.sort_values(['date', '_order'], ignore_index=True)
            return pd.DataFrame(
                {
                    'date': tidy['date'],
                    'question_id': self.question.id,
                    'measure': 'share',
                    'response_id': tidy['response_id'],
                    'response_label': tidy['response_id'].map(labels),
                    'value': tidy['value'].astype('float64'),
                    'unit': 'percent',
                    'cases': tidy['cases'].astype('Int64'),
                    'population': self.metadata.get('population', 'all_households'),
                }
            )
        if self.measure == 'index':
            labels = {'index': load_catalog().index_label}
        else:
            labels = {r.id: r.source_label for r in self.question.responses}
        tidy = wide.melt(
            id_vars=['date', 'cases'],
            value_vars=self.value_columns,
            var_name='response_id',
            value_name='value',
        )
        order = {rid: i for i, rid in enumerate(self.value_columns)}
        tidy['_order'] = tidy['response_id'].map(order)
        tidy = tidy.sort_values(['date', '_order'], ignore_index=True)
        out = pd.DataFrame(
            {
                'date': tidy['date'],
                'question_id': self.question.id,
                'measure': self.measure,
                'response_id': tidy['response_id'],
                'response_label': tidy['response_id'].map(labels),
                'value': tidy['value'].astype('float64'),
                'unit': UNITS[self.measure],
                'cases': tidy['cases'].astype('Int64'),
                'population': self.metadata.get('population', 'all_households'),
            }
        )
        return out

    def wide(self) -> pd.DataFrame:
        """One row per month and one column per response id, in catalog order."""
        if self.question.is_index:
            return self._trim(self.frame)[['date', 'index', 'preliminary']].copy()
        frame = self._trim(self.frame)[['date', *self.value_columns, 'cases']].copy()
        frame['cases'] = frame['cases'].astype('Int64')
        return frame

    @property
    def latest_period(self) -> str:
        return str(self.metadata['coverage']['latest_period'])

    def chart(self, **options: Any) -> alt.LayerChart:
        """Return an Altair chart. See `betteroff.charts.build_chart` for options."""
        from .charts import build_chart

        return build_chart(self, **options)

    def __repr__(self) -> str:
        return (
            f'<Dataset {self.question.id} ({self.question.table}) measure={self.measure} '
            f'{len(self._trim(self.frame))} months, latest {self.latest_period}>'
        )
