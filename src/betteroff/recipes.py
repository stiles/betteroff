"""Repeatable TOML recipes: settings in, files plus a run manifest out."""

from __future__ import annotations

import json
import logging
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .errors import InputError
from .themes import Theme, load_theme

log = logging.getLogger('betteroff')
RECIPE_SCHEMA_VERSION = 1
RUN_MANIFEST = 'betteroff-run.json'
JOB_KEYS = {
    'question',
    'name',
    'start',
    'end',
    'measure',
    'wide',
    'data_formats',
    'chart_formats',
    'rolling',
    'raw',
    'recessions',
    'width',
    'height',
    'theme',
    'font',
}
TOP_KEYS = {'schema_version', 'output_dir', 'jobs'}


@dataclass
class Job:
    question: str
    name: str
    start: str | None = None
    end: str | None = None
    measure: str = 'share'
    wide: bool = False
    data_formats: list[str] = field(default_factory=list)
    chart_formats: list[str] = field(default_factory=list)
    rolling: int | None = None
    raw: bool = True
    recessions: bool = False
    width: int | None = None
    height: int | None = None
    theme: Theme | None = None
    font: str | None = None


@dataclass
class Recipe:
    path: Path
    output_dir: Path
    jobs: list[Job]


def _str(value: Any) -> str | None:
    return None if value is None else str(value)


def load_recipe(path: Path) -> Recipe:
    from .catalog import load_catalog
    from .charts import CHART_FORMATS, resolve_font
    from .export import DATA_FORMATS
    from .models import check_measure

    try:
        raw = tomllib.loads(path.read_text('utf-8'))
    except FileNotFoundError:
        raise InputError(f'Recipe {path} not found.', 'Check the path.') from None
    except tomllib.TOMLDecodeError as exc:
        raise InputError(f'Recipe {path} is not valid TOML ({exc}).', 'Fix the syntax.') from None

    def bad(msg: str) -> InputError:
        return InputError(f'Recipe {path.name}: {msg}.', 'See docs/recipes.md for the format.')

    if raw.get('schema_version') != RECIPE_SCHEMA_VERSION:
        raise bad(f'schema_version must be {RECIPE_SCHEMA_VERSION}')
    if unknown := set(raw) - TOP_KEYS:
        raise bad(f'unknown setting(s) {sorted(unknown)}')
    jobs_raw = raw.get('jobs')
    if not isinstance(jobs_raw, list) or not jobs_raw:
        raise bad('add at least one [[jobs]] table')

    base = path.parent
    output_dir = (base / raw.get('output_dir', '.')).resolve()
    jobs: list[Job] = []
    names: set[str] = set()
    for i, j in enumerate(jobs_raw, start=1):
        if unknown := set(j) - JOB_KEYS:
            raise bad(f'job {i} has unknown setting(s) {sorted(unknown)}')
        if 'question' not in j:
            raise bad(f'job {i} needs a question')
        question = load_catalog().resolve(str(j['question']))
        check_measure(str(j.get('measure', 'share')))
        data_formats = list(j.get('data_formats', []))
        chart_formats = list(j.get('chart_formats', []))
        if not data_formats and not chart_formats:
            raise bad(f'job {i} needs data_formats or chart_formats')
        for f in data_formats:
            if f not in DATA_FORMATS:
                raise bad(f'job {i} has unknown data format "{f}"')
        for f in chart_formats:
            if f not in CHART_FORMATS:
                raise bad(f'job {i} has unknown chart format "{f}"')
        name = str(j.get('name') or question.id)
        if name in names:
            raise bad(f'two jobs write files named "{name}"; give one a different name')
        names.add(name)
        jobs.append(
            Job(
                question=question.id,
                name=name,
                start=_str(j.get('start')),
                end=_str(j.get('end')),
                measure=str(j.get('measure', 'share')),
                wide=bool(j.get('wide', False)),
                data_formats=data_formats,
                chart_formats=chart_formats,
                rolling=j.get('rolling'),
                raw=bool(j.get('raw', True)),
                recessions=bool(j.get('recessions', False)),
                width=j.get('width'),
                height=j.get('height'),
                theme=load_theme(j.get('theme'), base=base),
                font=resolve_font(_str(j.get('font'))),
            )
        )
    return Recipe(path=path.resolve(), output_dir=output_dir, jobs=jobs)


def run_recipe(path: Path, refresh: bool = False, offline: bool = False) -> list[Path]:
    from . import api
    from .charts import RECESSIONS_CHECKED, RECESSIONS_SOURCE, build_chart, save_chart
    from .export import render_data, sidecar, sidecar_path, write_sidecar
    from .models import Dataset, parse_date

    recipe = load_recipe(path)
    recipe.output_dir.mkdir(parents=True, exist_ok=True)
    loaded: dict[str, Dataset] = {}
    written: list[Path] = []
    run_jobs = []

    for job in recipe.jobs:
        question = api.describe(job.question)
        if question.id not in loaded:
            loaded[question.id] = api.get(question.id, refresh=refresh, offline=offline)
        base = loaded[question.id]
        ds = Dataset(
            question=base.question,
            frame=base.frame,
            metadata=base.metadata,
            measure=job.measure,
            start=parse_date(job.start, 'start'),
            end=parse_date(job.end, 'end'),
        )
        outputs = []
        for fmt in job.data_formats:
            out = recipe.output_dir / f'{job.name}.{fmt}'
            out.write_text(render_data(ds, fmt, job.wide), encoding='utf-8')
            write_sidecar(sidecar_path(out), sidecar(ds, out, {'format': fmt, 'wide': job.wide}))
            outputs.append(out)
        if job.chart_formats:
            chart = build_chart(
                ds,
                rolling=job.rolling,
                raw=job.raw,
                recessions=job.recessions,
                width=job.width,
                height=job.height,
                theme=job.theme,
                font=job.font,
            )
            for fmt in job.chart_formats:
                out = recipe.output_dir / f'{job.name}.{fmt}'
                save_chart(chart, out, fmt)
                details: dict[str, Any] = {
                    'format': fmt,
                    'chart': {
                        'rolling': job.rolling,
                        'raw': job.raw,
                        'recessions': job.recessions,
                        'theme': job.theme.record() if job.theme else None,
                        'font': job.font,
                    },
                }
                if job.recessions:
                    details['chart']['recession_dates'] = {
                        'source': RECESSIONS_SOURCE,
                        'checked': RECESSIONS_CHECKED,
                    }
                write_sidecar(sidecar_path(out), sidecar(ds, out, details))
                outputs.append(out)
        for out in outputs:
            log.info('Wrote %s', out)
        written.extend(outputs)
        run_jobs.append(
            {
                'question': question.id,
                'name': job.name,
                'outputs': [o.name for o in outputs],
                'snapshot': ds.metadata['snapshot'],
                'latest_period': ds.latest_period,
            }
        )

    manifest = {
        'recipe': recipe.path.name,
        'betteroff_version': __version__,
        'run_at': datetime.now(UTC).replace(microsecond=0).isoformat(),
        'refresh': refresh,
        'offline': offline,
        'jobs': run_jobs,
    }
    manifest_path = recipe.output_dir / RUN_MANIFEST
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    written.append(manifest_path)
    return written
