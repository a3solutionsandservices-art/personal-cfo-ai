"""Interpretation stage (PRD §6.6).

For each surviving signal, a Claude call (Sonnet/Opus-tier) drafts one
recommended action, choosing from the theme's action_templates and shaping it
to the lead's portfolio context (FR-INT-1). Every action MUST cite the
transcript span that triggered it; actions without a traceable trigger are
discarded as an anti-hallucination control (FR-INT-2, G3).
"""

from __future__ import annotations

from typing import Optional

from ..context import ContextProvider
from ..llm import Judge
from ..models import Action, Citation, Signal
from ..taxonomy import Taxonomy

_MAX_EXCERPT_CHARS = 280


class Interpreter:
    def __init__(self, judge: Judge, taxonomy: Taxonomy, context: ContextProvider) -> None:
        self.judge = judge
        self.taxonomy = taxonomy
        self.context = context

    def interpret(self, signal: Signal) -> Optional[Action]:
        theme = self.taxonomy.by_id(signal.theme_id)
        portfolio = self.context.portfolio_context()

        draft = self.judge.draft_action(signal.segment.text, theme, portfolio)

        # Anti-hallucination: the action must trace to a real transcript span.
        # The Segment carries the span; if there is no usable excerpt we discard.
        excerpt = signal.segment.text.strip()
        if not excerpt or not draft.get("recommendation"):
            return None
        excerpt = excerpt[:_MAX_EXCERPT_CHARS]

        action_type = draft.get("action_type") or theme.action_templates[0]
        if action_type not in theme.action_templates:
            action_type = theme.action_templates[0]

        return Action(
            signal_id=signal.id,
            theme_id=theme.id,
            action_type=action_type,
            recommendation=draft["recommendation"].strip(),
            rationale=draft.get("rationale", "").strip(),
            citation=Citation(
                item_guid=signal.item_guid,
                start_s=signal.segment.start_s,
                excerpt=excerpt,
            ),
            confidence=_norm_confidence(draft.get("confidence")),
            final=signal.final,
        )


def _norm_confidence(value) -> str:
    v = str(value or "medium").lower()
    return v if v in ("high", "medium", "low") else "medium"
