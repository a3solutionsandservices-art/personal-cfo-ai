"""End-to-end pipeline behaviour and acceptance criteria AC-3/4/6."""

from pathlib import Path

import pytest

from ai4tech.models import SourceItem
from ai4tech.pipeline import Pipeline


@pytest.fixture
def loaded_config(config, tmp_path):
    # Deliver markdown into a temp dir so the test can read the brief back.
    config.settings["delivery"]["output_dir"] = str(tmp_path / "out")
    return config


def _audio_item(guid="golden-ep-001"):
    return SourceItem(
        guid=guid, source_id="golden", title="Golden episode",
        audio_url="http://example/audio.mp3", show="Golden Test Podcast",
    )


def _preload_transcript(store, episode):
    store.put_transcript(
        episode["item_guid"], "fixture",
        " ".join(s["text"] for s in episode["segments"]),
        episode["segments"],
    )


def _build(loaded_config, store, items):
    pipeline = Pipeline(loaded_config, store, dry_run=False)
    pipeline._gather_items = lambda result: (_set_seen(result, items))
    return pipeline


def _set_seen(result, items):
    result.items_seen = len(items)
    return list(items)


def test_full_run_produces_grounded_brief(loaded_config, store, golden_episode):
    _preload_transcript(store, golden_episode)
    pipeline = _build(loaded_config, store, [_audio_item()])

    result = pipeline.run("run-1")

    assert result.items_processed == 1
    assert result.actions > 0
    assert result.brief is not None
    assert result.delivered_to  # markdown file path
    assert Path(result.delivered_to).exists()


def test_traceability_every_action_cites_a_real_span(loaded_config, store, golden_episode):
    """AC-4: every action resolves to a real transcript span at the cited time."""
    _preload_transcript(store, golden_episode)
    pipeline = _build(loaded_config, store, [_audio_item()])
    result = pipeline.run("run-trace")

    valid_starts = {s["start_s"] for s in golden_episode["segments"]}
    full_text = " ".join(s["text"] for s in golden_episode["segments"])
    for action in result.brief.actions:
        assert action.citation.item_guid == golden_episode["item_guid"]
        assert action.citation.start_s in valid_starts
        # the excerpt is a real substring of the transcript (anti-hallucination)
        assert action.citation.excerpt.strip()[:40] in full_text


def test_idempotent_rerun_does_not_resend(loaded_config, store, golden_episode):
    """AC-3: re-running the same run_id does not re-process or re-deliver."""
    _preload_transcript(store, golden_episode)
    pipeline = _build(loaded_config, store, [_audio_item()])

    first = pipeline.run("run-idem")
    out_dir = Path(loaded_config.settings["delivery"]["output_dir"])
    files_after_first = sorted(out_dir.glob("*.md"))

    second = pipeline.run("run-idem")  # same id
    files_after_second = sorted(out_dir.glob("*.md"))

    assert first.actions > 0
    assert second.items_processed == 0  # short-circuited (brief already sent)
    assert files_after_first == files_after_second  # no duplicate brief


def test_processed_items_skipped_on_new_run(loaded_config, store, golden_episode):
    """A new run after the item is processed skips it (exactly-once, G1)."""
    _preload_transcript(store, golden_episode)
    pipeline = _build(loaded_config, store, [_audio_item()])
    pipeline.run("run-a")

    pipeline2 = _build(loaded_config, store, [_audio_item()])
    result = pipeline2.run("run-b")
    assert result.items_skipped == 1
    assert result.items_processed == 0


def test_empty_run_delivers_no_signal_notice(loaded_config, store):
    """FR-DEL-3: an empty run sends a one-line notice, not silence."""
    pipeline = _build(loaded_config, store, [])
    result = pipeline.run("run-empty")
    assert result.actions == 0
    assert result.delivered_to
    content = Path(result.delivered_to).read_text()
    assert "No signal this period" in content


def test_cost_stays_under_budget(loaded_config, store, golden_episode):
    """AC-6: per-run cost is reported and within the configured ceiling."""
    _preload_transcript(store, golden_episode)
    pipeline = _build(loaded_config, store, [_audio_item()])
    result = pipeline.run("run-cost")
    budget = loaded_config.reliability["per_episode_budget_usd"]
    assert result.cost_usd <= budget


def test_audio_item_without_stt_is_quarantined(loaded_config, store):
    """FR-ORC-4: a failing item is quarantined, never silently dropped."""
    # No transcript preloaded and no STT -> empty transcript -> quarantine.
    pipeline = _build(loaded_config, store, [_audio_item("no-transcript")])
    result = pipeline.run("run-q")
    assert result.quarantined == 1
    assert store.quarantined()[0]["guid"] == "no-transcript"
