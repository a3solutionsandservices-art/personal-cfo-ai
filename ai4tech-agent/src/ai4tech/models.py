"""Core data models for the AI4Tech Intelligence Agent.

These dataclasses mirror the data model in the PRD (§9). They are plain,
serializable records passed between pipeline stages; persistence shapes live in
``state/store.py``.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def utcnow_iso() -> str:
    """ISO-8601 timestamp in UTC. Used for run ids and record timestamps."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SourceItem:
    """A new item yielded by a SourceAdapter (PRD §9 SourceItem).

    For podcasts ``audio_url`` is the enclosure URL. For text sources (e.g.
    newsletters) the body is carried in ``text`` and ``audio_url`` is empty,
    which lets the Transcriber stage short-circuit (FR-SRC-3 / G5).
    """

    guid: str
    source_id: str
    title: str
    audio_url: str = ""
    published_at: str = ""  # ISO-8601
    show: str = ""
    text: str = ""  # populated for already-textual sources

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Transcript:
    """Transcriber output: full text plus timestamped segments (FR-TR-2)."""

    item_guid: str
    text: str
    # each entry: {"start_s": float, "end_s": float, "text": str, "speaker": str|None}
    segments: list[dict] = field(default_factory=list)
    provider: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Segment:
    """A topic-coherent chunk of a transcript (PRD §9 Segment)."""

    item_guid: str
    start_s: float
    end_s: float
    text: str
    speaker: Optional[str] = None

    @property
    def id(self) -> str:
        """Stable id derived from source item + span, used for dedup/logging."""
        raw = f"{self.item_guid}:{self.start_s:.2f}:{self.end_s:.2f}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ThemeMatch:
    """Classifier output for one segment/theme pair (FR-CLF-1)."""

    theme_id: str
    confidence: float


@dataclass
class Signal:
    """A scored, theme-matched segment (PRD §9 Signal).

    ``embedding`` is attached for the novelty ledger (FR-SCO-3); it is not part
    of the equality identity.
    """

    id: str
    item_guid: str
    theme_id: str
    segment: Segment
    relevance: float = 0.0
    novelty: float = 0.0
    actionability: float = 0.0
    final: float = 0.0
    embedding: list[float] = field(default_factory=list)

    def to_record(self) -> dict:
        """Compact dict for the StateStore signal ledger (no full segment)."""
        return {
            "id": self.id,
            "item_guid": self.item_guid,
            "theme_id": self.theme_id,
            "text": self.segment.text,
            "relevance": self.relevance,
            "novelty": self.novelty,
            "actionability": self.actionability,
            "final": self.final,
        }


@dataclass(frozen=True)
class Citation:
    """Traceable trigger for an action (FR-INT-2)."""

    item_guid: str
    start_s: float
    excerpt: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Action:
    """A role-grounded recommended action (PRD §9 Action)."""

    signal_id: str
    theme_id: str
    action_type: str
    recommendation: str
    rationale: str
    citation: Citation
    confidence: str  # high | medium | low
    final: float = 0.0  # carried for ranking in the brief

    def to_dict(self) -> dict:
        d = asdict(self)
        d["citation"] = self.citation.to_dict()
        return d


@dataclass(frozen=True)
class ThemeDigest:
    theme_id: str
    line: str


@dataclass
class Brief:
    """The clustered, ranked output of one run (PRD §9 Brief)."""

    run_id: str
    generated_at: str
    digest: list[ThemeDigest] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    also_noted: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "digest": [asdict(d) for d in self.digest],
            "actions": [a.to_dict() for a in self.actions],
            "also_noted": list(self.also_noted),
        }
