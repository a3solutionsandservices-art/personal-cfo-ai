"""Scoring stage — the core of the product (PRD §6.5).

Each kept (segment, theme) pair receives three sub-scores in [0,1]:

  * relevance      — fit to the theme's signal_definition, given current_state.
  * novelty        — newness vs (a) the theme's stated current state and
                     (b) signals already surfaced in prior runs (embedding
                     similarity against the StateStore ledger). FR-SCO-3.
  * actionability  — whether a concrete next step plausibly follows.

  final = weight_theme * (w_r*relevance + w_n*novelty + w_a*actionability)

A configurable threshold gates what proceeds to interpretation; everything else
is logged but not surfaced (FR-SCO-4). Relevance and actionability come from an
LLM-as-judge; novelty combines an LLM judgement against current_state with an
embedding-similarity check (high similarity to a past signal suppresses novelty).
"""

from __future__ import annotations

from ..embeddings import Embedder
from ..llm import Judge
from ..models import Segment, Signal, ThemeMatch
from ..state import StateStore
from ..taxonomy import Taxonomy


class Scorer:
    def __init__(
        self,
        judge: Judge,
        taxonomy: Taxonomy,
        embedder: Embedder,
        store: StateStore,
        *,
        weight_relevance: float = 0.4,
        weight_novelty: float = 0.3,
        weight_actionability: float = 0.3,
        novelty_similarity_threshold: float = 0.86,
    ) -> None:
        self.judge = judge
        self.taxonomy = taxonomy
        self.embedder = embedder
        self.store = store
        self.w_r = weight_relevance
        self.w_n = weight_novelty
        self.w_a = weight_actionability
        self.novelty_similarity_threshold = novelty_similarity_threshold

    def score(self, segment: Segment, match: ThemeMatch) -> Signal:
        theme = self.taxonomy.by_id(match.theme_id)
        relevance, actionability = self.judge.relevance_actionability(segment.text, theme)

        # Novelty: LLM judgement against current_state, then suppress if the
        # signal is near-identical to something already surfaced (FR-SCO-3).
        novelty = self.judge.novelty_vs_state(segment.text, theme)
        embedding = self.embedder.embed(segment.text)
        similarity = self.store.max_similarity(theme.id, embedding)
        if similarity >= self.novelty_similarity_threshold:
            # Scale novelty down toward zero in proportion to how "seen" it is.
            suppression = (similarity - self.novelty_similarity_threshold) / (
                1.0 - self.novelty_similarity_threshold + 1e-9
            )
            novelty = novelty * (1.0 - min(1.0, suppression))

        relevance = _clamp(relevance)
        novelty = _clamp(novelty)
        actionability = _clamp(actionability)

        weighted = self.w_r * relevance + self.w_n * novelty + self.w_a * actionability
        final = theme.weight * weighted  # FR-SCO-1

        return Signal(
            id=f"{segment.id}:{theme.id}",
            item_guid=segment.item_guid,
            theme_id=theme.id,
            segment=segment,
            relevance=round(relevance, 4),
            novelty=round(novelty, 4),
            actionability=round(actionability, 4),
            final=round(final, 4),
            embedding=embedding,
        )


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
