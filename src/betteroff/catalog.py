"""Packaged catalog of supported tables. Reads only TOML, so it stays fast."""

from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from importlib import resources

from .errors import InputError

POLARITIES = ('positive', 'neutral', 'negative', 'nonresponse')


@dataclass(frozen=True)
class Response:
    id: str
    label: str
    source_label: str
    polarity: str


@dataclass(frozen=True)
class Break:
    date: date
    label: str
    comparable: bool


@dataclass(frozen=True)
class IndexSource:
    """Where a headline index lives on Michigan's main site."""

    history_url: str
    history_column: str
    current_url: str
    current_column: str


@dataclass(frozen=True)
class Breakdown:
    """One headline index within respondent groups, from a table such as 5b."""

    by: str  # Short name used with --by, e.g. "party"
    by_label: str  # "political party"
    banner: str  # Source row naming the grouping
    index_id: str  # The all-households index, e.g. "consumer_sentiment"
    index_title: str
    block: str  # Source label over this index's columns, e.g. "SENTIMENT INDEX"
    blocks: tuple[str, ...]  # Every index block in source order
    colors: tuple[str, ...]  # One per group, aligned with Question.responses


@dataclass(frozen=True)
class Question:
    """A catalog entry: a survey question's table, a headline index or a breakdown.

    Headline indexes (`kind == 'index'`) have no responses, use their code
    (ICS, ICC, ICE) as `table` and carry an `IndexSource`. Breakdowns
    (`kind == 'breakdown'`) list their groups as responses with polarity
    "group" and carry a `Breakdown`.
    """

    id: str
    table: str
    title: str
    wording: str
    responses: tuple[Response, ...]
    keywords: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    breaks: tuple[Break, ...] = ()
    monthly_since: date | None = None  # Only when later than the survey-wide date
    kind: str = 'table'
    label: str = ''  # Short series label for headline indexes or inflation series
    aliases: tuple[str, ...] = ()
    source: IndexSource | None = None
    breakdown: Breakdown | None = None

    @property
    def is_index(self) -> bool:
        return self.kind == 'index'

    @property
    def is_inflation(self) -> bool:
        return self.kind == 'inflation'

    @property
    def is_breakdown(self) -> bool:
        return self.kind == 'breakdown'

    def response(self, response_id: str) -> Response:
        for r in self.responses:
            if r.id == response_id:
                return r
        raise KeyError(response_id)

    def to_dict(self) -> dict[str, object]:
        if self.is_index:
            assert self.source is not None
            return {
                'id': self.id,
                'kind': self.kind,
                'code': self.table,
                'title': self.title,
                'label': self.label,
                'definition': self.wording,
                'notes': list(self.notes),
                'source_files': [self.source.history_url, self.source.current_url],
            }
        if self.is_breakdown:
            assert self.breakdown is not None
            return {
                'id': self.id,
                'kind': self.kind,
                'table': self.table,
                'title': self.title,
                'label': self.label,
                'aliases': list(self.aliases),
                'definition': self.wording,
                'index': self.breakdown.index_id,
                'by': self.breakdown.by,
                'by_label': self.breakdown.by_label,
                'groups': [
                    {
                        'id': r.id,
                        'label': r.label,
                        'source_label': r.source_label,
                        'population': f'{self.breakdown.by}:{r.id}',
                    }
                    for r in self.responses
                ],
                'notes': list(self.notes),
                'monthly_since': self.monthly_since.isoformat() if self.monthly_since else None,
            }
        return {
            'id': self.id,
            'kind': self.kind,
            'table': self.table,
            'title': self.title,
            'label': self.label,
            'aliases': list(self.aliases),
            'wording': self.wording,
            'responses': [r.__dict__ for r in self.responses],
            'notes': list(self.notes),
            'breaks': [
                {'date': b.date.isoformat(), 'label': b.label, 'comparable': b.comparable}
                for b in self.breaks
            ],
            'monthly_since': self.monthly_since.isoformat() if self.monthly_since else None,
        }


@dataclass(frozen=True)
class Headline:
    page_url: str
    base: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    landing_url: str
    attribution: str
    agreement_url: str
    population: str
    monthly_since: date
    index_label: str
    index_definition: str
    notes: tuple[str, ...]
    table_notes: tuple[str, ...]
    headline: Headline
    questions: tuple[Question, ...] = field(default_factory=tuple)

    def notes_for(self, question: Question) -> list[str]:
        """Catalog-wide notes that apply to this entry, then its own."""
        extra = self.headline.notes if question.is_index else self.table_notes
        return [*self.notes, *extra, *question.notes]

    def resolve(self, identifier: str) -> Question:
        key = identifier.strip().lower()
        key = re.sub(r'^table\s*', '', key)
        for q in self.questions:
            if key in (q.id, q.table.lower(), *q.aliases):
                return q
        candidates = [q.id for q in self.questions] + [a for q in self.questions for a in q.aliases]
        close = difflib.get_close_matches(key, candidates, n=3)
        hint = f'Did you mean {", ".join(close)}?' if close else ''
        raise InputError(
            f'Unknown question or table "{identifier}". {hint}'.strip(),
            'Run `betteroff list` or `betteroff search TEXT` to find an identifier.',
        )

    @property
    def breakdown_dimensions(self) -> list[str]:
        return list(dict.fromkeys(q.breakdown.by for q in self.questions if q.breakdown))

    def breakdown_of(self, question: Question, by: str) -> Question:
        """The breakdown of a headline index (or of another breakdown's index) by `by`."""
        key = by.strip().lower()
        available = ', '.join(self.breakdown_dimensions)
        if question.breakdown is not None:
            index_id = question.breakdown.index_id
        elif question.is_index:
            index_id = question.id
        else:
            raise InputError(
                f'--by works only with the headline indexes; {question.id} is table '
                f'{question.table}.',
                'Try `betteroff get ICS --by party`, or ICC or ICE.',
            )
        for q in self.questions:
            if q.breakdown and q.breakdown.index_id == index_id and q.breakdown.by == key:
                return q
        raise InputError(
            f'No breakdown "{by}" for {index_id}.', f'Use --by with one of: {available}.'
        )

    def search(self, text: str) -> list[Question]:
        terms = [t for t in re.split(r'\W+', text.lower()) if t]
        if not terms:
            return list(self.questions)
        scored = []
        for q in self.questions:
            fields = {
                'id': q.id.replace('_', ' '),
                'aliases': ' '.join(a.replace('_', ' ') for a in q.aliases),
                'title': q.title.lower(),
                'keywords': ' '.join(q.keywords).lower(),
                'wording': q.wording.lower(),
                'responses': ' '.join(r.label.lower() for r in q.responses),
            }
            weights = {
                'id': 3,
                'aliases': 3,
                'title': 3,
                'keywords': 2,
                'wording': 1,
                'responses': 1,
            }
            score = 0
            for term in terms:
                hit = 0
                for name, value in fields.items():
                    if re.search(rf'\b{re.escape(term)}', value):
                        hit = max(hit, weights[name])
                if term == q.table.lower():
                    hit = max(hit, 3)
                if not hit:
                    break
                score += hit
            else:
                scored.append((score, q))
        scored.sort(key=lambda pair: -pair[0])
        return [q for _, q in scored]


def _index(raw: dict) -> Question:
    return Question(
        id=raw['id'],
        table=raw['code'],
        title=raw['title'],
        wording=raw['definition'],
        responses=(),
        keywords=tuple(raw.get('keywords', ())),
        notes=tuple(raw.get('notes', ())),
        kind='index',
        label=raw['label'],
        source=IndexSource(
            history_url=raw['history_url'],
            history_column=raw['history_column'],
            current_url=raw['current_url'],
            current_column=raw['current_column'],
        ),
    )


def _question(raw: dict) -> Question:
    responses = tuple(Response(**r) for r in raw['responses'])
    for r in responses:
        if r.polarity not in POLARITIES:
            raise ValueError(f'{raw["id"]}: bad polarity {r.polarity!r}')
    return Question(
        id=raw['id'],
        table=str(raw['table']),
        title=raw['title'],
        wording=raw['wording'],
        responses=responses,
        keywords=tuple(raw.get('keywords', ())),
        aliases=tuple(raw.get('aliases', ())),
        notes=tuple(raw.get('notes', ())),
        breaks=tuple(
            Break(date.fromisoformat(b['date']), b['label'], bool(b['comparable']))
            for b in raw.get('breaks', ())
        ),
        monthly_since=date.fromisoformat(raw['monthly_since']) if 'monthly_since' in raw else None,
        kind=raw.get('kind', 'table'),
        label=raw.get('label', ''),
    )


def _breakdowns(raw: dict, indexes: tuple[Question, ...]) -> list[Question]:
    """One catalog entry per breakdown table and headline index."""
    by_id = {q.id: q for q in indexes}
    blocks = tuple(b['source_label'] for b in raw.get('breakdown_indexes', ()))
    out = []
    for t in raw.get('breakdowns', ()):
        groups = tuple(
            Response(id=g['id'], label=g['label'], source_label=g['source_label'], polarity='group')
            for g in t['groups']
        )
        for block in raw.get('breakdown_indexes', ()):
            index = by_id[block['index']]
            out.append(
                Question(
                    id=f'{index.id}_by_{t["by"]}',
                    table=str(t['table']),
                    title=f'{index.title} by {t["by_label"]}',
                    wording=(
                        f"Michigan's table {t['table']} publishes the {index.title} within each "
                        f'{t["by_label"]} group: {", ".join(g.label for g in groups)}.'
                    ),
                    responses=groups,
                    keywords=tuple(dict.fromkeys([*index.keywords, *t.get('keywords', ())])),
                    aliases=(f'{index.table.lower()}_by_{t["by"]}',),
                    notes=tuple(t.get('notes', ())),
                    monthly_since=(
                        date.fromisoformat(t['monthly_since']) if 'monthly_since' in t else None
                    ),
                    kind='breakdown',
                    label=f'{index.label} by {t["by_label"]}',
                    breakdown=Breakdown(
                        by=t['by'],
                        by_label=t['by_label'],
                        banner=t['banner'],
                        index_id=index.id,
                        index_title=index.title,
                        block=block['source_label'],
                        blocks=blocks,
                        colors=tuple(g['color'] for g in t['groups']),
                    ),
                )
            )
    return out


@cache
def load_catalog() -> Catalog:
    text = resources.files('betteroff').joinpath('data/catalog.toml').read_text('utf-8')
    raw = tomllib.loads(text)
    indexes = tuple(_index(i) for i in raw['indexes'])
    return Catalog(
        landing_url=raw['landing_url'],
        attribution=raw['attribution'],
        agreement_url=raw['agreement_url'],
        population=raw['population'],
        monthly_since=date.fromisoformat(raw['monthly_since']),
        index_label=raw['index_label'],
        index_definition=raw['index_definition'],
        notes=tuple(raw['notes']),
        table_notes=tuple(raw['table_notes']),
        headline=Headline(
            page_url=raw['headline']['page_url'],
            base=raw['headline']['base'],
            notes=tuple(raw['headline']['notes']),
        ),
        questions=(
            *indexes,
            *_breakdowns(raw, indexes),
            *(_question(q) for q in raw['questions']),
        ),
    )
