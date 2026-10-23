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
class Question:
    """A catalog entry: a survey question's table, or a headline index.

    Headline indexes (`kind == 'index'`) have no responses, use their code
    (ICS, ICC, ICE) as `table` and carry an `IndexSource`.
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

    @property
    def is_index(self) -> bool:
        return self.kind == 'index'

    @property
    def is_inflation(self) -> bool:
        return self.kind == 'inflation'

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
            weights = {'id': 3, 'aliases': 3, 'title': 3, 'keywords': 2, 'wording': 1, 'responses': 1}
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


@cache
def load_catalog() -> Catalog:
    text = resources.files('betteroff').joinpath('data/catalog.toml').read_text('utf-8')
    raw = tomllib.loads(text)
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
            *(_index(i) for i in raw['indexes']),
            *(_question(q) for q in raw['questions']),
        ),
    )
