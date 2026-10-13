import json
import math

import pandas as pd
import pytest

from betteroff.catalog import load_catalog
from betteroff.charts import (
    LINE_INVALID_MODE,
    _dodge,
    _font_file_names,
    build_chart,
    font_installed,
    monthly,
    prepare,
    recession_dates,
    response_colors,
    save_chart,
    trailing_mean,
)
from betteroff.errors import InputError
from betteroff.models import Dataset
from betteroff.themes import DEFAULT_THEME, list_themes, load_theme

alt = pytest.importorskip('altair')


def make_ds(
    question_id='government_policy',
    months=None,
    start='1978-01-01',
    periods=36,
    drop=(),
    measure='share',
    values=None,
):
    q = load_catalog().resolve(question_id)
    dates = pd.date_range(start, periods=periods, freq='MS')
    frame = pd.DataFrame({'date': dates})
    for i, r in enumerate(q.responses):
        frame[r.id] = [float(values[n]) if values and i == 0 else 10.0 + i for n in range(periods)]
    frame['total'] = 100.0
    frame['index'] = 100.0
    frame['cases'] = 1000.0
    frame = frame[~frame['date'].isin(pd.to_datetime(list(drop)))].reset_index(drop=True)
    meta = {
        'coverage': {'latest_period': f'{frame["date"].max():%Y-%m}'},
        'snapshot': {'retrieved_at': '2026-10-12T21:00:00+00:00'},
        'population': 'all_households',
    }
    return Dataset(question=q, frame=frame, metadata=meta, measure=measure)


def layers_of(spec):
    return spec['layer']


def layer_data(spec, layer):
    return spec['datasets'][layer['data']['name']]


def mark_type(layer):
    m = layer['mark']
    return m if isinstance(m, str) else m['type']


def test_monthly_reindex_makes_gaps_explicit():
    ds = make_ds(drop=['1978-05-01'])
    wide = monthly(ds.frame, ['good_job'])
    assert len(wide) == 36
    assert math.isnan(wide.loc[4, 'good_job'])


def test_trailing_mean_hand_checked():
    ds = make_ds(values=list(range(1, 37)))
    out = trailing_mean(monthly(ds.frame, ['good_job']), ['good_job'], 12)
    assert math.isnan(out.loc[10, 'good_job'])
    assert out.loc[11, 'good_job'] == 6.5  # mean of 1..12, December 1978
    assert out.loc[12, 'good_job'] == 7.5


def test_trailing_mean_needs_every_month():
    ds = make_ds(values=list(range(1, 37)), drop=['1978-05-01'])
    out = trailing_mean(monthly(ds.frame, ['good_job']), ['good_job'], 12)
    # Windows ending May 1978 through April 1979 include the missing month.
    assert out.loc[4:15, 'good_job'].isna().all()
    assert out.loc[16, 'good_job'] == pytest.approx(sum(range(6, 18)) / 12)


def test_rolling_is_computed_before_trimming():
    ds = make_ds(values=list(range(1, 37)))
    prep = prepare(ds, rolling=12, start='1979-01')
    assert prep.main.loc[0, 'date'] == pd.Timestamp('1979-01-01')
    assert prep.main.loc[0, 'good_job'] == 7.5
    assert prep.raw is not None and prep.raw.loc[0, 'good_job'] == 13


def test_rolling_must_be_at_least_two():
    with pytest.raises(InputError):
        prepare(make_ds(), rolling=1)


def test_default_start_skips_irregular_years():
    ds = make_ds(start='1975-01-01', periods=60)
    assert prepare(ds).start == pd.Timestamp('1978-01-01')
    assert prepare(ds, start='1975').start == pd.Timestamp('1975-01-01')


def test_spec_breaks_lines_at_missing_months():
    spec = build_chart(make_ds(drop=['1978-05-01'])).to_dict()
    lines = [la for la in layers_of(spec) if mark_type(la) == 'line']
    assert lines and all(la['mark']['invalid'] == LINE_INVALID_MODE for la in lines)
    rows = layer_data(spec, lines[-1])
    may = [r for r in rows if r['date'].startswith('1978-05') and r['response_id'] == 'good_job']
    assert may == [{**may[0], 'value': None}]


def test_spec_colors_follow_polarity_across_tables():
    def scale(question_id):
        spec = build_chart(make_ds(question_id)).to_dict()
        line = [la for la in layers_of(spec) if mark_type(la) == 'line'][-1]
        s = line['encoding']['color']['scale']
        return dict(zip(s['domain'], s['range'], strict=True))

    gov, finances = scale('government_policy'), scale('current_finances')
    palette = load_theme().colors
    assert gov['Good job'] == finances['Better off'] == palette['positive'][0]
    assert gov['Poor job'] == finances['Worse off'] == palette['negative'][0]
    assert gov['Only fair'] == finances['Same'] == palette['neutral'][0]


def test_nonresponse_lines_are_dashed():
    spec = build_chart(make_ds('business_conditions_12_months')).to_dict()
    line = [la for la in layers_of(spec) if mark_type(la) == 'line'][-1]
    dash = line['encoding']['strokeDash']['scale']
    styles = dict(zip(dash['domain'], dash['range'], strict=True))
    assert styles['Good times'] == [1, 0]
    assert styles["Don't know"] != [1, 0] and styles['No answer'] != styles["Don't know"]


def _contrast(hex_color):
    def channel(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(int(hex_color[i : i + 2], 16) / 255) for i in (1, 3, 5))
    return 1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05)


@pytest.mark.parametrize('theme', list_themes(), ids=lambda t: t.name)
def test_packaged_themes_are_legible(theme):
    for polarity in ('positive', 'negative'):
        assert _contrast(theme.colors[polarity][0]) >= 3, (theme.name, polarity)
    assert theme.colors['positive'][0] != theme.colors['negative'][0]
    assert theme.source.startswith('https://')


def test_unknown_theme():
    assert load_theme().name == DEFAULT_THEME == 'okabe-ito'
    with pytest.raises(InputError, match='Unknown theme'):
        load_theme('neon')
    with pytest.raises(InputError, match='not found'):
        load_theme('missing.toml')


def test_theme_from_file(tmp_path):
    path = tmp_path / 'house.toml'
    path.write_text('positive = ["#123456"]\nnegative = ["#654321"]\n')
    theme = load_theme(str(path))
    assert theme.name == 'house'
    assert theme.colors['positive'] == ('#123456',)
    assert theme.colors['neutral'] == load_theme().colors['neutral']
    spec = build_chart(make_ds(), theme=str(path)).to_dict()
    line = [la for la in layers_of(spec) if mark_type(la) == 'line'][-1]
    assert '#123456' in line['encoding']['color']['scale']['range']


def test_same_polarity_gets_distinct_shades():
    colors = response_colors(load_catalog().resolve('business_conditions_12_months'))
    assert colors['dk'] != colors['na']


def test_spec_share_axis_and_footer():
    spec = build_chart(make_ds()).to_dict()
    line = [la for la in layers_of(spec) if mark_type(la) == 'line'][-1]
    y = line['encoding']['y']
    assert y['scale']['domain'] == [0, 100]
    assert '%' in y['axis']['labelExpr']
    footer = layer_data(spec, layers_of(spec)[-1])[0]['text']
    assert 'Surveys of Consumers, table 34' in footer
    assert 'Latest month: December 1980' in footer
    assert 'Retrieved Oct 12, 2026' in footer
    assert spec['title']['text'] == "Opinions about the government's economic policy"


def test_spec_direct_labels_or_legend():
    spec = build_chart(make_ds()).to_dict()
    texts = [la for la in layers_of(spec) if mark_type(la) == 'text']
    labels = {r['label'] for la in texts for r in layer_data(spec, la) if 'label' in r}
    assert labels == {'Good job', 'Only fair', 'Poor job', "Don't know, no answer"}

    spec5 = build_chart(make_ds('business_conditions_12_months')).to_dict()
    line = [la for la in layers_of(spec5) if mark_type(la) == 'line'][-1]
    assert line['encoding']['color'].get('legend') is not None


def test_spec_recession_bands_are_clamped():
    ds = make_ds(start='1979-06-01', periods=24)
    spec = build_chart(ds, recessions=True, start='1980-03').to_dict()
    rects = [la for la in layers_of(spec) if mark_type(la) == 'rect']
    assert len(rects) == 1
    bands = layer_data(spec, rects[0])
    assert [(b['date'][:7], b['end'][:7]) for b in bands] == [('1980-03', '1980-07')]
    assert not [la for la in layers_of(build_chart(ds).to_dict()) if mark_type(la) == 'rect']


def test_spec_rolling_subtitle_and_raw_layer():
    spec = build_chart(make_ds(), rolling=12).to_dict()
    assert '12-month trailing average' in spec['title']['subtitle'][0]
    lines = [la for la in layers_of(spec) if mark_type(la) == 'line']
    assert len(lines) == 2
    spec = build_chart(make_ds(), rolling=12, raw=False).to_dict()
    assert len([la for la in layers_of(spec) if mark_type(la) == 'line']) == 1


def test_isolated_readings_are_drawn_as_points():
    ds = make_ds(
        start='1975-01-01',
        periods=48,
        drop=[
            d
            for d in pd.date_range('1975-01-01', '1977-12-01', freq='MS')
            if d.month not in (2, 5, 8, 11)
        ],
    )
    spec = build_chart(ds, start='1975').to_dict()
    points = [la for la in layers_of(spec) if mark_type(la) == 'point' and 'transform' not in la]
    assert points
    assert 'Gaps are months without a reading' in spec['title']['subtitle'][-1]


def test_index_measure_chart():
    spec = build_chart(make_ds(measure='index')).to_dict()
    line = [la for la in layers_of(spec) if mark_type(la) == 'line'][-1]
    assert line['encoding']['y']['scale']['domain'] == [0, 200]


def test_recession_list_is_pinned():
    dates = recession_dates()
    assert len(dates) == 13
    assert dates[-1][0].isoformat() == '2020-02-01'
    assert dates[-1][1].isoformat() == '2020-04-01'
    assert all(p < t for p, t in dates)


def test_dodge_keeps_labels_apart():
    out = _dodge([50, 51, 0.5, 0], gap=4, lo=0, hi=100)
    assert out[1] - out[0] >= 4
    assert out[2] - out[3] >= 4
    assert sorted(out) == [out[3], out[2], out[0], out[1]]


@pytest.mark.parametrize('fmt', ['svg', 'png', 'pdf', 'html', 'vl.json'])
def test_static_exports_render(tmp_path, fmt):
    pytest.importorskip('vl_convert')
    chart = build_chart(make_ds(), recessions=True)
    out = tmp_path / f'chart.{fmt}'
    save_chart(chart, out, fmt)
    data = out.read_bytes()
    assert len(data) > 1000
    if fmt == 'html':
        text = data.decode()
        assert 'cdn.jsdelivr' not in text and '<script src=' not in text
    if fmt == 'svg':
        assert b'<text' in data
    if fmt == 'vl.json':
        assert json.loads(data)['$schema'].startswith('https://vega.github.io/schema/vega-lite/v6')


def fonts_in(spec):
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ('font', 'labelFont', 'subtitleFont'):
                    found.add(v)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk({k: v for k, v in spec.items() if k != 'usermeta'})
    return found


def test_default_font_is_inter():
    spec = build_chart(make_ds()).to_dict()
    assert fonts_in(spec) == {'Inter, Helvetica, Arial, sans-serif'}
    assert spec['usermeta'] == {'betteroff': {'font': 'Inter'}}


def test_font_option_and_env(monkeypatch):
    spec = build_chart(make_ds(), font='IBM Plex Sans').to_dict()
    assert fonts_in(spec) == {'IBM Plex Sans, Helvetica, Arial, sans-serif'}
    monkeypatch.setenv('BETTEROFF_FONT', 'Atkinson Hyperlegible Next')
    spec = build_chart(make_ds()).to_dict()
    assert spec['usermeta']['betteroff']['font'] == 'Atkinson Hyperlegible Next'
    assert (
        build_chart(make_ds(), font='Geist').to_dict()['usermeta']['betteroff']['font'] == 'Geist'
    )


@pytest.mark.parametrize('bad', ['', '  ', 'Inter, Arial', '"Inter"', 'Inter;'])
def test_font_must_be_one_family(bad):
    with pytest.raises(InputError, match='single font family'):
        build_chart(make_ds(), font=bad)


def test_bad_font_env_names_the_variable(monkeypatch):
    monkeypatch.setenv('BETTEROFF_FONT', 'Inter, Arial')
    with pytest.raises(InputError, match='BETTEROFF_FONT'):
        build_chart(make_ds())


def test_font_installed_matches_file_names(tmp_path, monkeypatch):
    for name in ('InterVariable.ttf', 'IBMPlexSans-Regular.otf', 'Avenir Next.ttc', 'notes.txt'):
        (tmp_path / name).write_bytes(b'')
    monkeypatch.setattr('betteroff.charts.font_dirs', lambda: [tmp_path])
    _font_file_names.cache_clear()
    try:
        assert font_installed('Inter')
        assert font_installed('IBM Plex Sans')
        assert font_installed('Avenir Next')
        assert not font_installed('Montserrat')
        assert not font_installed('notes')
    finally:
        _font_file_names.cache_clear()


def test_missing_font_noted_on_static_export(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr('betteroff.charts.font_installed', lambda family: False)
    chart = build_chart(make_ds(), font='Nonesuch Sans')
    with caplog.at_level('INFO', logger='betteroff'):
        save_chart(chart, tmp_path / 'g.vl.json', 'vl.json')
        assert not caplog.records
        save_chart(chart, tmp_path / 'g.svg', 'svg')
    assert 'Nonesuch Sans not found' in caplog.text
