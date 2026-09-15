"""Vaggio scoring engine: pure functions shared by the monitor, the API and migrations."""

from watcher.scoring.engine import Classification, classify
from watcher.scoring.profile import PROFILE, ScoringProfile
from watcher.scoring.text import contains, normalize

__all__ = ["PROFILE", "Classification", "ScoringProfile", "classify", "contains", "normalize"]
