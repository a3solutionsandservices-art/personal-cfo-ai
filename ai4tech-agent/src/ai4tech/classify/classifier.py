"""Classification stage (PRD §6.4).

Each segment is classified against the taxonomy, returning zero or more
(theme_id, confidence) pairs — a segment may hit multiple themes or none
(FR-CLF-1). Matches below the confidence floor are dropped before scoring
(FR-CLF-3). The actual judgement is delegated to a Judge (Claude Haiku-tier in
production), prompted with each theme's signal_definition (FR-CLF-2).
"""

from __future__ import annotations

from ..llm import Judge
from ..models import Segment, ThemeMatch
from ..taxonomy import Taxonomy


class Classifier:
    def __init__(self, judge: Judge, taxonomy: Taxonomy, confidence_floor: float = 0.45) -> None:
        self.judge = judge
        self.taxonomy = taxonomy
        self.confidence_floor = confidence_floor

    def classify(self, segment: Segment) -> list[ThemeMatch]:
        raw = self.judge.classify(segment.text, self.taxonomy.themes)
        valid_ids = set(self.taxonomy.ids)
        matches = [
            ThemeMatch(theme_id=tid, confidence=conf)
            for tid, conf in raw
            if tid in valid_ids and conf >= self.confidence_floor
        ]
        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches
