"""Data exports, metadata sidecars and output-path rules."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import InputError

if TYPE_CHECKING:
    import pandas as pd

    from .models import Dataset

DATA_FORMATS = ('csv', 'json')


def data_format(path: Path) -> str | None:
    suffix = path.suffix.lower().lstrip('.')
    return suffix if suffix in DATA_FORMATS else None


def resolve_format(
    path: Path | None, requested: str | None, allowed: tuple[str, ...], infer: Any, default: str
) -> str:
    """Pick the output format from --format and the file extension; reject conflicts."""
    inferred = infer(path) if path else None
    if path and inferred is None and requested is None:
        raise InputError(
            f'Cannot tell the format of "{path.name}" from its extension.',
            f'Use one of: {", ".join("." + f for f in allowed)}, or pass --format.',
        )
    if requested and requested not in allowed:
        raise InputError(f'Unknown format "{requested}".', f'Use one of: {", ".join(allowed)}.')
    if requested and inferred and requested != inferred:
        raise InputError(
            f'--format {requested} contradicts the extension of "{path.name if path else ""}".',
            'Drop --format or change the file extension.',
        )
    return requested or inferred or default


def sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + '.meta.json')


def check_writable(path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise InputError(f'{path} already exists.', 'Pass --force to overwrite it.')
    if not path.parent.exists():
        raise InputError(f'Directory {path.parent} does not exist.', 'Create it first.')


def export_frame(dataset: Dataset, wide: bool) -> pd.DataFrame:
    frame = dataset.wide() if wide else dataset.data
    frame = frame.copy()
    frame['date'] = frame['date'].dt.strftime('%Y-%m-%d')
    return frame


def render_data(dataset: Dataset, fmt: str, wide: bool) -> str:
    frame = export_frame(dataset, wide)
    if fmt == 'csv':
        return str(frame.to_csv(index=False, lineterminator='\n', float_format='%.10g'))
    if fmt == 'json':
        return str(frame.to_json(orient='records', indent=2)) + '\n'
    raise InputError(f'Unknown data format "{fmt}".', f'Use one of: {", ".join(DATA_FORMATS)}.')


def sidecar(dataset: Dataset, output: Path | None, details: dict[str, Any]) -> dict[str, Any]:
    meta = dict(dataset.metadata)
    meta['export'] = {
        'file': output.name if output else None,
        'generated_at': datetime.now(UTC).replace(microsecond=0).isoformat(),
        'measure': dataset.measure,
        'start': dataset.start.isoformat() if dataset.start else None,
        'end': dataset.end.isoformat() if dataset.end else None,
        **details,
    }
    return meta


def write_sidecar(path: Path, meta: dict[str, Any]) -> None:
    path.write_text(json.dumps(meta, indent=2, default=str) + '\n', encoding='utf-8')
