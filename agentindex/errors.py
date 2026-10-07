"""Exceptions that carry a message meant for the user (or agent) running a command."""

from __future__ import annotations


class AgentIndexError(Exception):
    """Base class for expected, user-facing errors."""


class ConfigError(AgentIndexError):
    """The config file, a source directory, or an override is invalid."""


class QueryError(AgentIndexError):
    """A search query could not be turned into an index query."""


class NotFoundError(AgentIndexError):
    """A doc or section does not exist; ``suggestions`` lists close matches."""

    def __init__(self, message: str, suggestions: list[str] | None = None):
        super().__init__(message)
        self.suggestions = list(suggestions or [])
