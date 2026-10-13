"""Exceptions mapped to CLI exit codes."""

from __future__ import annotations


class BetteroffError(Exception):
    """Base class. `action` tells the user how to recover."""

    exit_code = 1

    def __init__(self, message: str, action: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.action = action

    def __str__(self) -> str:
        return f'{self.message} {self.action}' if self.action else self.message


class InputError(BetteroffError):
    """Invalid identifiers, options, paths or recipes."""

    exit_code = 2


class FetchError(BetteroffError):
    """Network failures, access pages or a missing offline snapshot."""

    exit_code = 3


class ValidationError(BetteroffError):
    """The source file no longer matches what the parser and catalog expect."""

    exit_code = 4


class MissingDependencyError(BetteroffError):
    exit_code = 2
