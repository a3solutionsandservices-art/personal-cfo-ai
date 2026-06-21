"""LLM judgement and synthesis backends (PRD §6.4-6.6, §10).

Stages do not call the Anthropic SDK directly. Instead they call a ``Judge``
that exposes the four LLM-shaped operations the pipeline needs:

  * classify(text, themes)                  -> [(theme_id, confidence)]   (FR-CLF-2)
  * relevance_actionability(text, theme)    -> (relevance, actionability) (FR-SCO-2)
  * novelty_vs_state(text, theme)           -> novelty in [0,1]           (FR-SCO-3)
  * draft_action(text, theme, portfolio)    -> action dict                (FR-INT-1)

Two interchangeable backends implement it:

  * ``AnthropicJudge`` — real Claude calls. Classification/scoring run on a
    Haiku-tier model for cost; interpretation runs on Sonnet/Opus. Model IDs
    come from settings.yaml, never hardcoded.
  * ``HeuristicJudge`` — deterministic, dependency-free. Lets the whole
    pipeline (and the test suite) run with no API key, and gives ``dry-run``
    something real to do.

``make_judge`` picks the real backend when an API key and the SDK are present,
otherwise the heuristic one — so the same code path serves both.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Callable, Optional, Protocol

from .taxonomy import Theme

_WORD = re.compile(r"[a-z0-9]+")
_ACTION_CUES = {
    "benchmark", "cost", "policy", "guardrail", "pattern", "metric", "scorecard",
    "pilot", "evaluate", "framework", "control", "autonomy", "governance",
    "throughput", "evidence", "pricing", "migration", "rollout", "eval",
}
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "at", "is",
    "are", "be", "as", "with", "that", "this", "it", "not", "signal", "new",
    "across", "their", "they", "what", "from", "into", "about", "by", "an",
}


class Judge(Protocol):  # pragma: no cover - structural
    def classify(self, text: str, themes: list[Theme]) -> list[tuple[str, float]]: ...
    def relevance_actionability(self, text: str, theme: Theme) -> tuple[float, float]: ...
    def novelty_vs_state(self, text: str, theme: Theme) -> float: ...
    def draft_action(self, text: str, theme: Theme, portfolio: str) -> dict: ...


# --------------------------------------------------------------------------- #
# Retry helper (FR-ORC-4): bounded retries with exponential backoff.
# --------------------------------------------------------------------------- #
def retry(fn: Callable, *, max_retries: int = 4, base: float = 2.0, exc=(Exception,)):
    """Run ``fn`` with bounded exponential backoff. Re-raises the last error."""
    last: Optional[BaseException] = None
    for attempt in range(max_retries):
        try:
            return fn()
        except exc as e:  # noqa: BLE001 - intentional broad retry boundary
            last = e
            if attempt == max_retries - 1:
                break
            time.sleep(base * (2 ** attempt) + random.uniform(0, 0.5))
    assert last is not None
    raise last


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2}


def _split_signal_def(theme: Theme) -> tuple[set[str], set[str]]:
    """Positive vs 'NOT signal' negative keyword sets for a theme."""
    sd = theme.signal_definition
    low = sd.lower()
    idx = low.find("not signal")
    pos_text = sd[:idx] if idx >= 0 else sd
    neg_text = sd[idx:] if idx >= 0 else ""
    pos = _tokens(theme.name + " " + theme.description + " " + pos_text)
    neg = _tokens(neg_text)
    return pos - neg, neg


# --------------------------------------------------------------------------- #
# Heuristic backend — deterministic, offline.
# --------------------------------------------------------------------------- #
class HeuristicJudge:
    """Keyword-overlap judge. Monotonic in lexical fit; fully deterministic."""

    def classify(self, text: str, themes: list[Theme]) -> list[tuple[str, float]]:
        toks = _tokens(text)
        if not toks:
            return []
        out: list[tuple[str, float]] = []
        for theme in themes:
            pos, neg = _split_signal_def(theme)
            if not pos:
                continue
            hits = len(toks & pos)
            penalty = len(toks & neg)
            conf = hits / (len(pos) ** 0.5)  # reward overlap, damp by theme breadth
            conf = max(0.0, conf - 0.15 * penalty)
            conf = min(1.0, conf)
            if conf > 0:
                out.append((theme.id, round(conf, 3)))
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    def relevance_actionability(self, text: str, theme: Theme) -> tuple[float, float]:
        toks = _tokens(text)
        pos, _ = _split_signal_def(theme)
        relevance = min(1.0, (len(toks & pos) / (len(pos) ** 0.5)) if pos else 0.0)
        # Actionability: concreteness cues + presence of action vocabulary.
        cue_hits = len(toks & _ACTION_CUES)
        has_number = 1 if re.search(r"\d", text) else 0
        actionability = min(1.0, 0.18 * cue_hits + 0.2 * has_number)
        return round(relevance, 3), round(actionability, 3)

    def novelty_vs_state(self, text: str, theme: Theme) -> float:
        if not theme.current_state:
            return 1.0
        toks = _tokens(text)
        state = _tokens(theme.current_state)
        if not state or not toks:
            return 1.0
        overlap = len(toks & state) / len(state)
        return round(max(0.0, 1.0 - overlap), 3)

    def draft_action(self, text: str, theme: Theme, portfolio: str) -> dict:
        action_type = theme.action_templates[0]
        snippet = " ".join(text.split()[:18])
        return {
            "action_type": action_type,
            "recommendation": (
                f"{action_type.replace('-', ' ').capitalize()}: {theme.name} — "
                f"act on \"{snippet}…\""
            ),
            "rationale": (
                f"Relevant to {theme.name} given current state. "
                f"Source segment discusses: {snippet}…"
            ),
            "confidence": "medium",
        }


# --------------------------------------------------------------------------- #
# Anthropic backend — real Claude calls.
# --------------------------------------------------------------------------- #
_CLASSIFY_SYSTEM = (
    "You are a precise classifier for an AI4Tech intelligence pipeline. Decide "
    "which themes a transcript segment is a genuine SIGNAL for, using each "
    "theme's signal_definition as the contract. Honour the 'NOT signal' "
    "exclusions strictly. Return only themes the segment substantively matches."
)
_SCORE_SYSTEM = (
    "You are an LLM-as-judge for an AI4Tech intelligence pipeline. Score how "
    "well a segment fits a theme's signal_definition (relevance) and whether a "
    "concrete next step for the lead's mandate plausibly follows (actionability)."
)
_INTERPRET_SYSTEM = (
    "You advise an AI4Tech lead driving AI-native SDLC and PDLC across a "
    "Payments Technology org. Draft ONE concrete, role-grounded recommended "
    "action for a surfaced signal, choosing from the theme's action_templates "
    "and shaping it to the lead's portfolio. Be specific and brief."
)


class AnthropicJudge:
    """Real Claude-backed judge (PRD §6.4-6.6). Model IDs are injected."""

    def __init__(
        self,
        classifier_model: str,
        scorer_model: str,
        interpreter_model: str,
        *,
        max_retries: int = 4,
        backoff_base: float = 2.0,
        client=None,
    ) -> None:
        if client is None:
            import anthropic  # imported lazily; only needed for the real backend

            client = anthropic.Anthropic()
        self._client = client
        self.classifier_model = classifier_model
        self.scorer_model = scorer_model
        self.interpreter_model = interpreter_model
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.total_cost_usd = 0.0  # accumulated for the per-run budget report (AC-6)

    # -- low-level call returning parsed JSON via output_config.format -------
    def _json_call(self, model: str, system: str, user: str, schema: dict) -> dict:
        def _do():
            resp = self._client.messages.create(
                model=model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
            self._track_cost(model, resp)
            text = next((b.text for b in resp.content if b.type == "text"), "{}")
            return json.loads(text)

        return retry(_do, max_retries=self.max_retries, base=self.backoff_base)

    def _track_cost(self, model: str, resp) -> None:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        rates = _PRICE_PER_MTOK.get(model, (3.0, 15.0))
        self.total_cost_usd += (
            getattr(usage, "input_tokens", 0) / 1_000_000 * rates[0]
            + getattr(usage, "output_tokens", 0) / 1_000_000 * rates[1]
        )

    def classify(self, text: str, themes: list[Theme]) -> list[tuple[str, float]]:
        theme_block = "\n".join(
            f"- {t.id}: {t.name}. SIGNAL: {t.signal_definition}" for t in themes
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["matches"],
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["theme_id", "confidence"],
                        "properties": {
                            "theme_id": {"type": "string", "enum": [t.id for t in themes]},
                            "confidence": {"type": "number"},
                        },
                    },
                }
            },
        }
        user = f"THEMES:\n{theme_block}\n\nSEGMENT:\n{text}\n\nReturn matching themes only."
        data = self._json_call(self.classifier_model, _CLASSIFY_SYSTEM, user, schema)
        return [
            (m["theme_id"], float(m["confidence"]))
            for m in data.get("matches", [])
        ]

    def relevance_actionability(self, text: str, theme: Theme) -> tuple[float, float]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["relevance", "actionability"],
            "properties": {
                "relevance": {"type": "number"},
                "actionability": {"type": "number"},
            },
        }
        user = (
            f"THEME: {theme.name}\nSIGNAL DEFINITION: {theme.signal_definition}\n"
            f"CURRENT STATE: {theme.current_state}\n\nSEGMENT:\n{text}\n\n"
            "Score relevance and actionability in [0,1]."
        )
        data = self._json_call(self.scorer_model, _SCORE_SYSTEM, user, schema)
        return float(data["relevance"]), float(data["actionability"])

    def novelty_vs_state(self, text: str, theme: Theme) -> float:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["novelty"],
            "properties": {"novelty": {"type": "number"}},
        }
        user = (
            f"THEME: {theme.name}\nCURRENT STATE (what we already know/do):\n"
            f"{theme.current_state}\n\nSEGMENT:\n{text}\n\n"
            "How new is this relative to current state? novelty in [0,1] "
            "(1 = genuinely new, 0 = restates what we already know)."
        )
        data = self._json_call(self.scorer_model, _SCORE_SYSTEM, user, schema)
        return float(data["novelty"])

    def draft_action(self, text: str, theme: Theme, portfolio: str) -> dict:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["action_type", "recommendation", "rationale", "confidence"],
            "properties": {
                "action_type": {"type": "string", "enum": theme.action_templates},
                "recommendation": {"type": "string"},
                "rationale": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            },
        }
        user = (
            f"PORTFOLIO CONTEXT:\n{portfolio}\n\n"
            f"THEME: {theme.name}\nCURRENT STATE: {theme.current_state}\n"
            f"ACTION TEMPLATES: {theme.action_templates}\n\n"
            f"SIGNAL SEGMENT:\n{text}\n\n"
            "Draft one recommended action: a one-line recommendation, a "
            "2-3 sentence rationale, and a confidence band."
        )
        return self._json_call(self.interpreter_model, _INTERPRET_SYSTEM, user, schema)


# Rough $/MTok (input, output) for the per-run cost report (PRD §14, AC-6).
_PRICE_PER_MTOK = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}


def make_judge(models: dict, reliability: dict, *, force_heuristic: bool = False) -> Judge:
    """Pick the real backend when usable, else the deterministic one."""
    if force_heuristic or not os.environ.get("ANTHROPIC_API_KEY"):
        return HeuristicJudge()
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return HeuristicJudge()
    return AnthropicJudge(
        classifier_model=models["classifier"],
        scorer_model=models["scorer"],
        interpreter_model=models["interpreter"],
        max_retries=int(reliability.get("max_retries", 4)),
        backoff_base=float(reliability.get("backoff_base_s", 2.0)),
    )
