"""Betteroff: clean data and charts from the Michigan consumer surveys.

Independent project; not affiliated with or endorsed by the University of Michigan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:
    from ._version import __version__
except ImportError:  # running from a source checkout without a build
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version('betteroff')
    except PackageNotFoundError:
        __version__ = '0.0.0+unknown'

if TYPE_CHECKING:
    from .api import BetteroffWarning, describe, get, list_questions, search
    from .catalog import Question
    from .models import Dataset

__all__ = [
    'BetteroffWarning',
    'Dataset',
    'Question',
    '__version__',
    'describe',
    'get',
    'list_questions',
    'search',
]

_LAZY = {
    'BetteroffWarning': 'api',
    'describe': 'api',
    'get': 'api',
    'list_questions': 'api',
    'search': 'api',
    'Question': 'catalog',
    'Dataset': 'models',
}


def __getattr__(name: str) -> Any:
    # Keeps `import betteroff` and the fast CLI paths free of pandas and HTTPX.
    if name in _LAZY:
        import importlib

        module = importlib.import_module(f'.{_LAZY[name]}', __name__)
        return getattr(module, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
