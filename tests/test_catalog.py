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
        polarities = [r.polarity for r in q.responses]
        assert polarities.count('positive') == 1, q.id
        assert polarities.count('negative') == 1, q.id
        assert set(polarities) <= set(POLARITIES)
        assert len({r.id for r in q.responses}) == len(q.responses)


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
