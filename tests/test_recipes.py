import json

import pytest

from betteroff.errors import InputError
from betteroff.recipes import load_recipe, run_recipe


def write(tmp_path, text):
    path = tmp_path / 'betteroff.toml'
    path.write_text(text)
    return path


RECIPE = """
schema_version = 1
output_dir = 'output'

[[jobs]]
question = 'government_policy'
start = '1978-01-01'
data_formats = ['csv', 'json']
chart_formats = ['vl.json']
rolling = 3
recessions = true

[[jobs]]
question = '34'
name = 'gov_index'
measure = 'index'
wide = true
data_formats = ['csv']
"""


def test_run_writes_declared_outputs_and_manifest(source, gov_xls, tmp_path):
    source.queue = [gov_xls]
    written = run_recipe(write(tmp_path, RECIPE))
    out = tmp_path / 'output'
    names = sorted(p.name for p in written)
    assert names == sorted(
        [
            'government_policy.csv',
            'government_policy.json',
            'government_policy.vl.json',
            'gov_index.csv',
            'betteroff-run.json',
        ]
    )
    assert (out / 'government_policy.csv.meta.json').exists()
    assert (out / 'gov_index.csv').read_text().startswith('date,index,cases')
    manifest = json.loads((out / 'betteroff-run.json').read_text())
    assert manifest['jobs'][0]['snapshot']['sha256']
    assert source.calls == 1  # one fetch per question per run

    # Re-running replaces declared outputs without --force.
    run_recipe(write(tmp_path, RECIPE))


@pytest.mark.parametrize(
    ('text', 'message'),
    [
        ('schema_version = 2\n[[jobs]]\nquestion="34"\ndata_formats=["csv"]', 'schema_version'),
        ('schema_version = 1', 'at least one'),
        ('schema_version = 1\n[[jobs]]\nquestion="34"', 'data_formats or chart_formats'),
        ('schema_version = 1\n[[jobs]]\nquestion="34"\ndata_formats=["xlsx"]', 'xlsx'),
        ('schema_version = 1\n[[jobs]]\nquestion="34"\ndata_formats=["csv"]\nrollin=3', 'rollin'),
        (
            'schema_version = 1\n[[jobs]]\nquestion="34"\ndata_formats=["csv"]\n'
            '[[jobs]]\nquestion="government_policy"\ndata_formats=["json"]',
            'different name',
        ),
        ('schema_version = ', 'not valid TOML'),
    ],
)
def test_recipe_errors(tmp_path, text, message):
    with pytest.raises(InputError, match=message):
        load_recipe(write(tmp_path, text))


def test_relative_output_dir(tmp_path):
    recipe = load_recipe(write(tmp_path, RECIPE))
    assert recipe.output_dir == (tmp_path / 'output').resolve()


def test_theme_names_and_relative_files(tmp_path):
    (tmp_path / 'house.toml').write_text('positive = ["#123456"]\nnegative = ["#654321"]\n')
    text = (
        'schema_version = 1\n'
        '[[jobs]]\nquestion = "34"\nchart_formats = ["html"]\ntheme = "brbg"\n'
        '[[jobs]]\nquestion = "30"\nchart_formats = ["html"]\ntheme = "house.toml"\n'
        '[[jobs]]\nquestion = "6"\nchart_formats = ["html"]\n'
    )
    jobs = load_recipe(write(tmp_path, text)).jobs
    assert [j.theme.name for j in jobs] == ['brbg', 'house', 'okabe-ito']


def test_unknown_theme_in_recipe(tmp_path):
    text = (
        'schema_version = 1\n[[jobs]]\nquestion = "34"\nchart_formats = ["html"]\ntheme = "neon"\n'
    )
    with pytest.raises(InputError, match='Unknown theme'):
        load_recipe(write(tmp_path, text))


def test_font_in_recipe(tmp_path, monkeypatch):
    monkeypatch.setenv('BETTEROFF_FONT', 'Work Sans')
    text = (
        'schema_version = 1\n'
        '[[jobs]]\nquestion = "34"\nchart_formats = ["html"]\nfont = "IBM Plex Sans"\n'
        '[[jobs]]\nquestion = "30"\nchart_formats = ["html"]\n'
    )
    jobs = load_recipe(write(tmp_path, text)).jobs
    assert [j.font for j in jobs] == ['IBM Plex Sans', 'Work Sans']


def test_bad_font_in_recipe(tmp_path):
    text = (
        'schema_version = 1\n[[jobs]]\nquestion = "34"\nchart_formats = ["html"]\n'
        'font = "Inter, Arial"\n'
    )
    with pytest.raises(InputError, match='single font family'):
        load_recipe(write(tmp_path, text))
