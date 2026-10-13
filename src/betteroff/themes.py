"""Chart color themes. Reads only TOML, so listing themes stays fast."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from .errors import InputError

DEFAULT_THEME = 'okabe-ito'
POLARITIES = ('positive', 'neutral', 'negative', 'nonresponse')


@dataclass(frozen=True)
class Theme:
    name: str
    description: str
    colors: dict[str, tuple[str, ...]]  # polarity -> shades
    nonresponse_label: str
    index: str
    source: str = ''

    def record(self) -> dict[str, Any]:
        """What a sidecar needs to reproduce the colors."""
        return {
            'name': self.name,
            'source': self.source or None,
            'colors': {p: list(c) for p, c in self.colors.items()},
            'nonresponse_label': self.nonresponse_label,
            'index': self.index,
        }


def _theme(name: str, raw: dict[str, Any], defaults: dict[str, Any]) -> Theme:
    merged = {**defaults, **raw}
    try:
        colors = {p: tuple(merged[p]) for p in POLARITIES}
    except KeyError as exc:
        raise InputError(
            f'Theme "{name}" is missing {exc.args[0]} colors.',
            'Add a list of hex colors for it; see docs/charts.md.',
        ) from None
    return Theme(
        name=name,
        description=str(merged.get('description', '')),
        colors=colors,
        nonresponse_label=str(merged['nonresponse_label']),
        index=str(merged['index']),
        source=str(merged.get('source', '')),
    )


@cache
def _packaged() -> tuple[dict[str, Any], dict[str, Any]]:
    text = resources.files('betteroff').joinpath('data/themes.toml').read_text('utf-8')
    raw = tomllib.loads(text)
    return raw['defaults'], raw['themes']


def list_themes() -> list[Theme]:
    defaults, packaged = _packaged()
    return [_theme(name, raw, defaults) for name, raw in packaged.items()]


def load_theme(theme: str | Path | Theme | None = None, base: Path | None = None) -> Theme:
    """A packaged theme by name, or a .toml file with the same keys as a packaged theme.

    Relative file paths resolve against `base` (a recipe's folder) when given.
    """
    if isinstance(theme, Theme):
        return theme
    name = str(theme or DEFAULT_THEME)
    defaults, packaged = _packaged()
    if name in packaged:
        return _theme(name, packaged[name], defaults)
    path = Path(name).expanduser()
    if base is not None and not path.is_absolute():
        path = base / path
    if path.suffix == '.toml':
        try:
            raw = tomllib.loads(path.read_text('utf-8'))
        except FileNotFoundError:
            raise InputError(f'Theme file {path} not found.', 'Check the path.') from None
        except tomllib.TOMLDecodeError as exc:
            raise InputError(
                f'Theme file {path} is not valid TOML ({exc}).', 'Fix the syntax.'
            ) from None
        return _theme(path.stem, raw, defaults)
    raise InputError(
        f'Unknown theme "{name}".',
        f'Use one of {", ".join(packaged)}, or a path to a .toml theme file. '
        'Run `betteroff themes` to preview them.',
    )
