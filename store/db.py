"""SQLite store composition root.

One database file and one connection are intentional so Artifact commits,
Source admission and ledger writes remain atomic. Domain behavior lives in
dedicated repository modules, not in this facade.
"""

from __future__ import annotations

try:
    from .artifacts import ArtifactRepository
    from .dreams import DreamRepository
    from .extraction import ExtractionRepository
    from .ledger import LedgerRepository
    from .metrics import StoreMetricsRepository
    from .runtime_episodes import RuntimeEpisodeRepository
    from .runtime_state import RuntimeStateRepository
    from .sources import SourceRepository
    from .sqlite import SqliteDatabase
except ImportError:  # standalone imports from the store directory
    from artifacts import ArtifactRepository
    from dreams import DreamRepository
    from extraction import ExtractionRepository
    from ledger import LedgerRepository
    from metrics import StoreMetricsRepository
    from runtime_episodes import RuntimeEpisodeRepository
    from runtime_state import RuntimeStateRepository
    from sources import SourceRepository
    from sqlite import SqliteDatabase


class DB:
    """Compose repositories over one SQLite connection."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.sqlite = SqliteDatabase(path)
        self.artifacts = ArtifactRepository(self.sqlite)
        self.sources = SourceRepository(self.sqlite)
        self.extraction = ExtractionRepository(self.sqlite)
        self.ledger = LedgerRepository(self.sqlite)
        self.runtime_state = RuntimeStateRepository(self.sqlite)
        self.runtime_episodes = RuntimeEpisodeRepository(self.sqlite)
        self.dreams = DreamRepository(self.sqlite)
        self.metrics = StoreMetricsRepository(self.sqlite, self.extraction)

    @property
    def conn(self):
        return self.sqlite.conn

    def close(self) -> None:
        self.sqlite.close()
