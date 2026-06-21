"""Novelty suppression via the signal ledger (AC-5, FR-SCO-3)."""

from ai4tech.classify import Classifier
from ai4tech.embeddings import make_embedder
from ai4tech.llm import HeuristicJudge
from ai4tech.models import Segment
from ai4tech.score import Scorer


def _make_scorer(config, store):
    judge = HeuristicJudge()
    scorer = Scorer(
        judge, config.taxonomy, make_embedder("hash-256"), store,
        weight_relevance=config.scoring["weight_relevance"],
        weight_novelty=config.scoring["weight_novelty"],
        weight_actionability=config.scoring["weight_actionability"],
        novelty_similarity_threshold=config.scoring["novelty_similarity_threshold"],
    )
    return judge, scorer


def test_reprocessing_same_signal_suppresses_novelty(config, golden_episode, store):
    """The same segment scored twice surfaces no new novelty on the second pass."""
    judge, scorer = _make_scorer(config, store)
    clf = Classifier(judge, config.taxonomy, confidence_floor=config.scoring["classify_confidence_floor"])

    # Pick a clearly on-theme signal segment (the agentic-coding one).
    seg_data = golden_episode["segments"][1]
    seg = Segment(
        item_guid=golden_episode["item_guid"],
        start_s=seg_data["start_s"], end_s=seg_data["end_s"], text=seg_data["text"],
    )
    match = clf.classify(seg)[0]

    first = scorer.score(seg, match)
    assert first.novelty > 0.0
    # Surface it to the ledger, as the pipeline would.
    store.add_signal(first)

    second = scorer.score(seg, match)
    # AC-5: identical content -> high embedding similarity -> novelty suppressed.
    assert second.novelty < first.novelty
    assert second.novelty <= 0.05
