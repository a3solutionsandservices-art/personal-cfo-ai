"""Brief assembly stage (PRD §6.7).

Clusters actions by theme, ranks by final score within theme, merges
near-duplicate actions across episodes, and applies a run-level cap so the
brief stays scannable; overflow is summarized as "also noted" (FR-BRF-1..3).
The brief opens with a one-line-per-theme digest, then the ranked actions
(FR-BRF-4).
"""

from __future__ import annotations

import re

from ..models import Action, Brief, ThemeDigest
from ..taxonomy import Taxonomy

_WORD = re.compile(r"[a-z0-9]+")


class BriefAssembler:
    def __init__(self, taxonomy: Taxonomy, max_actions: int = 12, dedup_similarity: float = 0.9) -> None:
        self.taxonomy = taxonomy
        self.max_actions = max_actions
        self.dedup_similarity = dedup_similarity

    def assemble(self, run_id: str, generated_at: str, actions: list[Action]) -> Brief:
        deduped = self._dedup(actions)

        # Cluster by theme, then rank by final score within theme (FR-BRF-1).
        by_theme: dict[str, list[Action]] = {}
        for a in deduped:
            by_theme.setdefault(a.theme_id, []).append(a)
        for items in by_theme.values():
            items.sort(key=lambda a: a.final, reverse=True)

        # Order themes by their best action's score, preserving taxonomy order
        # as the tie-break for determinism.
        order = {tid: i for i, tid in enumerate(self.taxonomy.ids)}
        themes_ranked = sorted(
            by_theme.keys(),
            key=lambda t: (-max(a.final for a in by_theme[t]), order.get(t, 999)),
        )

        ranked: list[Action] = []
        for tid in themes_ranked:
            ranked.extend(by_theme[tid])

        kept = ranked[: self.max_actions]
        overflow = ranked[self.max_actions :]

        digest = [
            ThemeDigest(
                theme_id=tid,
                line=self._digest_line(tid, by_theme[tid], kept),
            )
            for tid in themes_ranked
            if any(a.theme_id == tid for a in kept)
        ]

        also_noted = [
            f"[{self._theme_name(a.theme_id)}] {a.recommendation}" for a in overflow
        ]

        return Brief(
            run_id=run_id,
            generated_at=generated_at,
            digest=digest,
            actions=kept,
            also_noted=also_noted,
        )

    # ----------------------------------------------------------------- helpers
    def _dedup(self, actions: list[Action]) -> list[Action]:
        """Merge near-duplicate actions (FR-BRF-2), keeping the higher-scored."""
        kept: list[Action] = []
        for a in sorted(actions, key=lambda x: x.final, reverse=True):
            if any(
                b.theme_id == a.theme_id and _jaccard(a.recommendation, b.recommendation) >= self.dedup_similarity
                for b in kept
            ):
                continue
            kept.append(a)
        return kept

    def _digest_line(self, theme_id: str, theme_actions: list[Action], kept: list[Action]) -> str:
        n = sum(1 for a in kept if a.theme_id == theme_id)
        top = max(theme_actions, key=lambda a: a.final)
        name = self._theme_name(theme_id)
        plural = "s" if n != 1 else ""
        return f"{name}: {n} action{plural}. Top: {top.recommendation}"

    def _theme_name(self, theme_id: str) -> str:
        try:
            return self.taxonomy.by_id(theme_id).name
        except KeyError:
            return theme_id


def _jaccard(a: str, b: str) -> float:
    sa = set(_WORD.findall(a.lower()))
    sb = set(_WORD.findall(b.lower()))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
