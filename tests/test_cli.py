import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from betteroff.cli import app
from betteroff.errors import FetchError

from .conftest import build_xls, gov_rows

runner = CliRunner()


def run(*args):
    return runner.invoke(app, list(args))


def test_help_lists_commands():
    result = run('--help')
    assert result.exit_code == 0
    for cmd in ('search', 'list', 'describe', 'get', 'chart', 'run', 'cache'):
        assert cmd in result.stdout


def test_search_piped_is_tab_separated():
    result = run('search', 'government')
    assert result.exit_code == 0
    assert result.stdout.splitlines()[0] == (
        "34\tgovernment_policy\tOpinions about the government's economic policy"
    )


def test_search_without_matches():
    result = run('search', 'zzzz')
    assert result.exit_code == 0
    assert result.stdout == ''
    assert 'No questions match' in result.stderr


def test_list_includes_every_question(catalog):
    lines = run('list').stdout.splitlines()
    assert len(lines) == len(catalog.questions)


def test_describe_without_cache():
    result = run('describe', '34')
    assert result.exit_code == 0
    assert 'As to the economic policy' in result.stdout
    assert 'No cached data yet' in result.stdout


def test_describe_with_cache_shows_recent_values(source, gov_xls):
    source.queue = [gov_xls]
    assert run('get', '34', '-q').exit_code == 0
    result = run('describe', 'government_policy')
    assert 'Latest data' in result.stdout
    assert 'Dec 1979' in result.stdout


def test_describe_json():
    data = json.loads(run('describe', '34', '--json').stdout)
    assert data['table'] == '34'


def test_get_piped_is_clean_csv(source, gov_xls):
    source.queue = [gov_xls]
    result = run('get', 'government_policy')
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0] == (
        'date,question_id,measure,response_id,response_label,value,unit,cases,population'
    )
    assert all(line[:4].isdigit() for line in lines[1:])
    assert 'Checking source' in result.stderr


def test_get_alias_matches_id(source, gov_xls):
    source.queue = [gov_xls]
    assert run('get', '34').stdout == run('get', 'government_policy').stdout


def test_get_quiet_drops_notices(source, gov_xls):
    source.queue = [gov_xls]
    result = run('get', '34', '-q')
    assert result.stderr == ''


def test_get_json_format(source, gov_xls):
    source.queue = [gov_xls]
    data = json.loads(run('get', '34', '--format', 'json', '--wide').stdout)
    assert data[0]['good_job'] == 36


def test_get_table_format(source, gov_xls):
    source.queue = [gov_xls]
    result = run('get', '34', '-f', 'table')
    assert '1979-12' in result.stdout
    assert 'Showing the last 24 of 26 months' in result.stderr


def test_get_output_writes_sidecar(source, gov_xls, tmp_path):
    source.queue = [gov_xls]
    out = tmp_path / 'gov.csv'
    result = run('get', '34', '--wide', '-o', str(out))
    assert result.exit_code == 0, result.stderr
    assert result.stdout == ''
    assert out.read_text().startswith('date,good_job,fair,poor_job,dk_na,cases')
    meta = json.loads((tmp_path / 'gov.csv.meta.json').read_text())
    assert meta['export']['wide'] is True


def test_get_meta_for_stdout(source, gov_xls, tmp_path):
    source.queue = [gov_xls]
    meta = tmp_path / 'm.json'
    result = run('get', '34', '--meta', str(meta))
    assert result.exit_code == 0
    assert json.loads(meta.read_text())['export']['file'] is None


def test_exit_code_invalid_input(source, gov_xls, tmp_path):
    source.queue = [gov_xls]
    out = tmp_path / 'gov.csv'
    out.write_text('keep me')
    result = run('get', '34', '-o', str(out))
    assert result.exit_code == 2
    assert '--force' in result.stderr
    assert out.read_text() == 'keep me'
    assert run('get', '34', '-o', str(tmp_path / 'x.csv'), '-f', 'json').exit_code == 2
    assert run('get', 'nope').exit_code == 2
    assert run('get', '34', '--refresh', '--offline').exit_code == 2
    assert run('get', '34', '--bogus-flag').exit_code == 2


def test_exit_code_fetch_failure(source):
    source.queue = [FetchError('Could not reach the source.', 'Try later.')]
    result = run('get', '34')
    assert result.exit_code == 3
    assert result.stdout == ''
    assert 'error: Could not reach the source.' in result.stderr
    assert 'Try later.' in result.stderr


def test_exit_code_validation_failure(source, gov):
    source.queue = [build_xls(gov, gov_rows(), labels=['Good', 'Fair', 'Poor', 'DK'])]
    result = run('get', '34')
    assert result.exit_code == 4
    assert 'headers changed' in result.stderr


def test_debug_reraises(source):
    source.queue = [FetchError('boom')]
    result = run('--debug', 'get', '34')
    assert isinstance(result.exception, FetchError)


def test_offline_warning_survives_quiet(source, gov_xls):
    source.queue = [gov_xls]
    run('get', '34', '-q')
    result = run('get', '34', '--offline', '-q')
    assert result.exit_code == 0
    assert 'warning: Offline' in result.stderr


def test_chart_writes_html_and_sidecar(source, gov_xls, tmp_path, monkeypatch):
    pytest.importorskip('vl_convert')
    source.queue = [gov_xls]
    monkeypatch.chdir(tmp_path)
    result = run('chart', '34', '--rolling', '3', '--recessions')
    assert result.exit_code == 0, result.stderr
    assert (tmp_path / 'government_policy.html').exists()
    meta = json.loads((tmp_path / 'government_policy.html.meta.json').read_text())
    assert meta['export']['chart']['recession_dates']['source'].startswith('NBER')
    assert run('chart', '34').exit_code == 2  # refuses to overwrite


def test_chart_missing_extra_message(monkeypatch):
    from betteroff import charts
    from betteroff.errors import MissingDependencyError

    def missing():
        raise MissingDependencyError('Charts need extras.', "Run `uv add 'betteroff[charts]'`.")

    monkeypatch.setattr(charts, 'require_altair', missing)
    result = run('chart', '34')
    assert result.exit_code == 2
    assert 'betteroff[charts]' in result.stderr


def test_chart_theme_recorded(source, gov_xls, tmp_path):
    source.queue = [gov_xls]
    out = tmp_path / 'g.vl.json'
    assert run('chart', '34', '--theme', 'brbg', '-o', str(out)).exit_code == 0
    meta = json.loads((tmp_path / 'g.vl.json.meta.json').read_text())
    assert meta['export']['chart']['theme']['name'] == 'brbg'
    assert meta['export']['chart']['theme']['colors']['positive'][0] == '#018571'


def test_chart_font_recorded(source, gov_xls, tmp_path, monkeypatch):
    source.queue = [gov_xls]
    out = tmp_path / 'g.vl.json'
    assert run('chart', '34', '--font', 'Montserrat', '-o', str(out)).exit_code == 0
    meta = json.loads((tmp_path / 'g.vl.json.meta.json').read_text())
    assert meta['export']['chart']['font'] == 'Montserrat'
    assert json.loads(out.read_text())['title']['font'].startswith('Montserrat, ')
    monkeypatch.setenv('BETTEROFF_FONT', 'Work Sans')
    assert run('chart', '34', '-o', str(out), '--force').exit_code == 0
    meta = json.loads((tmp_path / 'g.vl.json.meta.json').read_text())
    assert meta['export']['chart']['font'] == 'Work Sans'


def test_bad_font_fails_before_fetching(source, tmp_path):
    result = run('chart', '34', '--font', 'Inter, Arial', '-o', str(tmp_path / 'g.html'))
    assert result.exit_code == 2
    assert source.calls == 0


def test_unknown_theme_fails_before_fetching(source, tmp_path):
    result = run('chart', '34', '--theme', 'neon', '-o', str(tmp_path / 'g.html'))
    assert result.exit_code == 2
    assert 'betteroff themes' in result.stderr
    assert source.calls == 0


def test_themes_command():
    lines = run('themes').stdout.splitlines()
    names = [line.split('\t')[0] for line in lines]
    assert names[0] == 'okabe-ito'
    assert {'puor', 'brbg', 'rdbu', 'tol'} <= set(names)


def test_chart_vl_json(source, gov_xls, tmp_path):
    source.queue = [gov_xls]
    out = tmp_path / 'g.vl.json'
    assert run('chart', '34', '-o', str(out)).exit_code == 0
    assert json.loads(out.read_text())['layer']


def test_cache_commands(source, gov_xls, isolated_cache):
    assert run('cache', 'path').stdout.strip() == str(isolated_cache.root)
    assert 'No cached data' in run('cache', 'info').stderr
    source.queue = [gov_xls]
    run('get', '34', '-q')
    assert 'government_policy' in run('cache', 'info').stdout


def test_cache_prune(source, gov, gov_xls, isolated_cache):
    source.queue = [gov_xls]
    run('get', '34', '-q')
    source.queue = [build_xls(gov, [*gov_rows(), (1980, 1, [30, 30, 38, 2])])]
    run('get', '34', '-q', '--refresh')
    old = isolated_cache.snapshots('government_policy')[0]
    dry = run('cache', 'prune', '--dry-run')
    assert dry.exit_code == 0 and 'Would remove 1 snapshot file' in dry.stderr
    assert dry.stdout.strip() == str(isolated_cache.snapshot_path(old.sha256))
    assert len(isolated_cache.snapshots('government_policy')) == 2
    assert run('cache', 'prune').exit_code == 0
    assert len(isolated_cache.snapshots('government_policy')) == 1
    assert run('cache', 'prune', '--keep', '0').exit_code == 2


def test_search_imports_no_heavy_modules():
    code = (
        'import sys\n'
        'from betteroff.cli import app\n'
        'try:\n'
        "    app(['search', 'government'])\n"
        'except SystemExit:\n'
        '    pass\n'
        "print([m for m in ('pandas', 'httpx', 'altair', 'xlrd') if m in sys.modules])\n"
    )
    result = subprocess.run(
        [sys.executable, '-c', code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip().splitlines()[-1] == '[]'
