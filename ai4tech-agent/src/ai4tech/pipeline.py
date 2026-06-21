"""Pipeline orchestration (PRD §4, §8).

Wires the linear pipeline behind its interfaces and runs it once, idempotently:

    SourceAdapter -> Transcriber -> Segmenter -> Classifier -> Scorer
                  -> Interpreter -> BriefAssembler -> Deliverer

Idempotency (FR-ORC-1): processed items are skipped by GUID, and a run that has
already delivered its brief will not re-send it. Each item is processed inside a
try/except so a permanently failing item is quarantined and reported, never
silently dropped (FR-ORC-4). Surfaced signals are written to the novelty ledger
so future runs can suppress repeats (FR-SCO-3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .brief import BriefAssembler
from .classify import Classifier
from .config import AppConfig
from .context import StaticContextProvider
from .deliver import make_deliverer
from .embeddings import make_embedder
from .interpret import Interpreter
from .llm import make_judge
from .models import Action, Brief, Signal, SourceItem, utcnow_iso
from .score import Scorer
from .segment import Segmenter
from .sources import make_adapter
from .state import StateStore
from .transcribe import make_transcriber

log = logging.getLogger("ai4tech")


@dataclass
class RunResult:
    run_id: str
    items_seen: int = 0
    items_processed: int = 0
    items_skipped: int = 0
    signals_surfaced: int = 0
    actions: int = 0
    quarantined: int = 0
    delivered_to: str = ""
    brief: Brief | None = None
    cost_usd: float = 0.0
    log_lines: list[str] = field(default_factory=list)

    def log_line(self, msg: str) -> None:
        self.log_lines.append(msg)
        log.info(msg)


class Pipeline:
    def __init__(self, config: AppConfig, store: StateStore, *, dry_run: bool = False) -> None:
        self.config = config
        self.store = store
        self.dry_run = dry_run

        # dry-run forces the deterministic judge so M0 can execute the full
        # pipeline with no external dependency and write a run log.
        self.judge = make_judge(
            config.models, config.reliability, force_heuristic=dry_run
        )
        self.taxonomy = config.taxonomy
        self.transcriber = make_transcriber(config.transcription, store)
        self.segmenter = Segmenter(
            target_words=int(config.segmenter["target_words"]),
            min_words=int(config.segmenter["min_words"]),
        )
        self.classifier = Classifier(
            self.judge, self.taxonomy,
            confidence_floor=float(config.scoring["classify_confidence_floor"]),
        )
        self.embedder = make_embedder(config.models.get("embeddings", "hash-256"))
        self.scorer = Scorer(
            self.judge, self.taxonomy, self.embedder, store,
            weight_relevance=float(config.scoring["weight_relevance"]),
            weight_novelty=float(config.scoring["weight_novelty"]),
            weight_actionability=float(config.scoring["weight_actionability"]),
            novelty_similarity_threshold=float(config.scoring["novelty_similarity_threshold"]),
        )
        self.context = StaticContextProvider(config.portfolio_path, self.taxonomy)
        self.interpreter = Interpreter(self.judge, self.taxonomy, self.context)
        self.assembler = BriefAssembler(
            self.taxonomy,
            max_actions=int(config.brief["max_actions"]),
            dedup_similarity=float(config.brief["dedup_similarity"]),
        )
        self.threshold = float(config.scoring["threshold"])

    # ---------------------------------------------------------------- public
    def run(self, run_id: str | None = None) -> RunResult:
        run_id = run_id or _default_run_id()
        result = RunResult(run_id=run_id)
        self.store.start_run(run_id)

        # Idempotency: if this run already delivered, don't re-send (FR-ORC-1).
        if self.store.run_brief_sent(run_id):
            result.log_line(f"run {run_id} already delivered; nothing to do")
            return result

        items = self._gather_items(result)
        actions: list[Action] = []
        surfaced: list[Signal] = []

        for item in items:
            if self.store.is_processed(item.guid):
                result.items_skipped += 1
                continue
            try:
                item_actions, item_signals = self._process_item(item, result)
                actions.extend(item_actions)
                surfaced.extend(item_signals)
                self.store.mark_processed(item.guid, item.source_id, item.title)
                result.items_processed += 1
            except Exception as e:  # noqa: BLE001 - quarantine boundary (FR-ORC-4)
                self.store.quarantine(item.guid, "process", repr(e))
                result.quarantined += 1
                result.log_line(f"QUARANTINED {item.guid}: {e!r}")

        # Persist surfaced signals to the novelty ledger (FR-SCO-3/FR-ORC-3).
        for sig in surfaced:
            self.store.add_signal(sig)
        result.signals_surfaced = len(surfaced)

        brief = self.assembler.assemble(run_id, utcnow_iso(), actions)
        result.brief = brief
        result.actions = len(brief.actions)
        result.cost_usd = round(getattr(self.judge, "total_cost_usd", 0.0), 4)

        self._deliver(brief, result)
        self.store.finish_run(
            run_id,
            status="delivered" if result.delivered_to else "dry-run",
            brief_sent=bool(result.delivered_to),
            log="\n".join(result.log_lines),
        )
        return result

    # --------------------------------------------------------------- internals
    def _gather_items(self, result: RunResult) -> list[SourceItem]:
        items: list[SourceItem] = []
        for feed in self.config.enabled_feeds:
            try:
                adapter = make_adapter(feed)
                feed_items = adapter.fetch_new()
                items.extend(feed_items)
                result.log_line(f"feed {feed.id}: {len(feed_items)} items")
            except Exception as e:  # noqa: BLE001
                result.log_line(f"feed {feed.id} FAILED: {e!r}")
        result.items_seen = len(items)
        return items

    def _process_item(self, item: SourceItem, result: RunResult) -> tuple[list[Action], list[Signal]]:
        transcript = self.transcriber.transcribe(item)
        if not transcript.text:
            raise RuntimeError("empty transcript (no STT available for audio item)")

        segments = self.segmenter.segment(transcript)
        actions: list[Action] = []
        surfaced: list[Signal] = []

        for segment in segments:
            for match in self.classifier.classify(segment):
                signal = self.scorer.score(segment, match)
                if signal.final < self.threshold:
                    continue  # logged-but-not-surfaced (FR-SCO-4)
                surfaced.append(signal)
                action = self.interpreter.interpret(signal)
                if action is not None:  # uncited actions discarded (FR-INT-2)
                    actions.append(action)
        result.log_line(
            f"item {item.guid}: {len(segments)} segments, "
            f"{len(surfaced)} surfaced, {len(actions)} actions"
        )
        return actions, surfaced

    def _deliver(self, brief: Brief, result: RunResult) -> None:
        if self.dry_run:
            result.log_line("dry-run: skipping delivery")
            return
        deliverer = make_deliverer(self.config.delivery)
        where = deliverer.deliver(brief)
        result.delivered_to = where
        result.log_line(f"delivered to {where}")


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
