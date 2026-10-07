"""AgentIndex: a searchable knowledge base for coding agents.

Markdown docs in the repository are indexed into SQLite (FTS5) so agents can
search them by keyword and read only what they need, instead of loading one
huge CLAUDE.md into every session.
"""

__version__ = "0.2.0"

from .config import Config, load_config  # noqa: E402
from .errors import AgentIndexError, ConfigError, NotFoundError, QueryError  # noqa: E402
from .store import KnowledgeIndex, SyncReport  # noqa: E402

__all__ = [
    "AgentIndexError",
    "Config",
    "ConfigError",
    "KnowledgeIndex",
    "NotFoundError",
    "QueryError",
    "SyncReport",
    "__version__",
    "load_config",
]
