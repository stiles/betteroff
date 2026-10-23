import pytest

from betteroff.catalog import POLARITIES
from betteroff.errors import InputError


def test_identifiers_are_unique(catalog):
    ids = [q.id for q in catalog.questions]
    tables = [q.table for q in catalog.questions]
    assert len(ids) == len(set(ids))
    assert len(tables) == len(set(tables))


def test_every_question_supports_the_index(catalog):
    for q in catalog.questions:
        if q.is_index or q.is_inflation:
            continue
        polarities = [r.polarity for r in q.responses]
        assert polarities.count('positive') == 1, q.id
        assert polarities.count('negative') == 1, q.id
        assert set(polarities) <= set(POLARITIES)
        assert len({r.id for r in q.responses}) == len(q.responses)


def test_inflation_questions(catalog):
    for q in catalog.questions:
        if not q.is_inflation:
            continue
        assert q.table in ('32', '33')
        assert len(q.responses) == 10
        assert q.responses[0].id == 'down'
        assert q.responses[1].id == 'same'
        assert q.responses[-1].id == 'dk_na'


@pytest.mark.parametrize(
    'identifier', ['government_policy', '34', 'Table 34', ' GOVERNMENT_POLICY ']
)
def test_resolve_aliases(catalog, identifier):
    assert catalog.resolve(identifier).id == 'government_policy'


def test_unknown_identifier_suggests(catalog):
    with pytest.raises(InputError) as exc:
        catalog.resolve('goverment_policy')
    assert 'government_policy' in str(exc.value)
    assert exc.value.exit_code == 2


def test_search_ranks_titles_first(catalog):
    results = catalog.search('government')
    assert results[0].id == 'government_policy'


def test_search_requires_every_term(catalog):
    assert [q.id for q in catalog.search('unemployment expectations')] == [
        'unemployment_expectations'
    ]
    assert catalog.search('zzzz') == []


def test_irregular_questions_record_monthly_start(catalog):
    assert catalog.resolve('10').monthly_since.isoformat() == '2011-07-01'
    assert catalog.resolve('34').monthly_since is None


@pytest.mark.parametrize(
    ('identifier', 'expected'),
    [
        ('ICS', 'consumer_sentiment'),
        ('ics', 'consumer_sentiment'),
        ('current_conditions', 'current_conditions'),
        ('ICE', 'consumer_expectations'),
    ],
)
def test_headline_indexes_resolve_by_code(catalog, identifier, expected):
    q = catalog.resolve(identifier)
    assert q.id == expected and q.is_index and q.responses == ()
    assert q.source is not None and q.source.history_url.endswith('.csv')


def test_headline_indexes_lead_the_catalog(catalog):
    assert [q.table for q in catalog.questions[:3]] == ['ICS', 'ICC', 'ICE']
    assert catalog.search('consumer sentiment')[0].id == 'consumer_sentiment'


def test_notes_depend_on_the_source(catalog):
    embargo = catalog.table_notes[0]
    assert embargo in catalog.notes_for(catalog.resolve('34'))
    ics_notes = catalog.notes_for(catalog.resolve('ICS'))
    assert embargo not in ics_notes
    assert any('preliminary' in n for n in ics_notes)
