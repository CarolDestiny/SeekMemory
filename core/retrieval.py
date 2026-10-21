from __future__ import annotations

from dataclasses import dataclass

from .artifact import Artifact


@dataclass(frozen=True)
class RetrievalCandidate:
    artifact: Artifact
    activation: float = 0.0
    lexical: float = 0.0
