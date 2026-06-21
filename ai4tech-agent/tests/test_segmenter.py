"""Segmentation (PRD §6.3, FR-SEG-1/2)."""

from ai4tech.models import Transcript
from ai4tech.segment import Segmenter


def test_segments_retain_timestamps_and_guid(golden_episode):
    transcript = Transcript(
        item_guid=golden_episode["item_guid"],
        text="",
        segments=golden_episode["segments"],
    )
    segs = Segmenter(target_words=120, min_words=20).segment(transcript)
    assert segs, "expected at least one segment"
    for s in segs:
        assert s.item_guid == golden_episode["item_guid"]
        assert s.end_s >= s.start_s
        assert s.text


def test_empty_transcript_yields_nothing():
    assert Segmenter().segment(Transcript(item_guid="x", text="", segments=[])) == []


def test_groups_toward_target_words():
    raw = [{"start_s": i, "end_s": i + 1, "text": "word " * 50, "speaker": "a"} for i in range(10)]
    segs = Segmenter(target_words=100, min_words=20).segment(Transcript("x", "", raw))
    # 500 words / ~100 target -> multiple segments, not one giant chunk
    assert len(segs) >= 3
