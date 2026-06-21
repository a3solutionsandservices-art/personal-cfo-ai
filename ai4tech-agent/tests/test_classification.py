"""Classifier accuracy on the golden set (AC-1) and noise rejection (AC-2)."""

from ai4tech.classify import Classifier
from ai4tech.embeddings import make_embedder
from ai4tech.llm import HeuristicJudge
from ai4tech.models import Segment
from ai4tech.score import Scorer


def _segments(episode):
    return [
        Segment(
            item_guid=episode["item_guid"],
            start_s=s["start_s"],
            end_s=s["end_s"],
            text=s["text"],
            speaker=s.get("speaker"),
        )
        for s in episode["segments"]
    ]


def test_classifier_accuracy_on_golden(config, golden_episode, golden_labels):
    judge = HeuristicJudge()
    clf = Classifier(judge, config.taxonomy, confidence_floor=config.scoring["classify_confidence_floor"])

    correct = 0
    total_signal = 0
    for seg, label in zip(_segments(golden_episode), golden_labels):
        matches = clf.classify(seg)
        top = matches[0].theme_id if matches else None
        if label == "noise":
            continue
        total_signal += 1
        if top == label:
            correct += 1

    # AC-1: classifier should get the dominant theme right on most signal segments.
    accuracy = correct / total_signal
    assert accuracy >= 0.8, f"golden accuracy {accuracy:.2f} below bar"


def test_noise_stays_below_threshold(config, golden_episode, golden_labels, store):
    """AC-2: off-topic / intro-level segments must not clear the score gate."""
    judge = HeuristicJudge()
    clf = Classifier(judge, config.taxonomy, confidence_floor=config.scoring["classify_confidence_floor"])
    scorer = Scorer(
        judge, config.taxonomy, make_embedder("hash-256"), store,
        weight_relevance=config.scoring["weight_relevance"],
        weight_novelty=config.scoring["weight_novelty"],
        weight_actionability=config.scoring["weight_actionability"],
        novelty_similarity_threshold=config.scoring["novelty_similarity_threshold"],
    )
    threshold = config.scoring["threshold"]

    false_positives = 0
    for seg, label in zip(_segments(golden_episode), golden_labels):
        if label != "noise":
            continue
        for match in clf.classify(seg):
            sig = scorer.score(seg, match)
            if sig.final >= threshold:
                false_positives += 1

    assert false_positives == 0, "noise segment surfaced above threshold"


def test_signal_segments_surface(config, golden_episode, golden_labels, store):
    """The complement of AC-2: genuine signal segments DO clear the gate."""
    judge = HeuristicJudge()
    clf = Classifier(judge, config.taxonomy, confidence_floor=config.scoring["classify_confidence_floor"])
    scorer = Scorer(
        judge, config.taxonomy, make_embedder("hash-256"), store,
        weight_relevance=config.scoring["weight_relevance"],
        weight_novelty=config.scoring["weight_novelty"],
        weight_actionability=config.scoring["weight_actionability"],
        novelty_similarity_threshold=config.scoring["novelty_similarity_threshold"],
    )
    threshold = config.scoring["threshold"]

    surfaced_themes = set()
    for seg, label in zip(_segments(golden_episode), golden_labels):
        if label == "noise":
            continue
        for match in clf.classify(seg):
            sig = scorer.score(seg, match)
            if sig.final >= threshold:
                surfaced_themes.add(sig.theme_id)

    # the majority of labelled themes should surface at least once
    expected = {l for l in golden_labels if l != "noise"}
    assert len(surfaced_themes & expected) >= 0.6 * len(expected)
