"""StateStore primitives: idempotency, transcript cache, novelty ledger."""

from ai4tech.models import Segment, Signal


def test_processed_idempotency(store):
    assert not store.is_processed("g1")
    store.mark_processed("g1", "feed", "title")
    assert store.is_processed("g1")
    # marking again is harmless (FR-ORC-1)
    store.mark_processed("g1", "feed", "title")
    assert store.is_processed("g1")


def test_transcript_cache(store):
    assert store.get_transcript("g1") is None
    store.put_transcript("g1", "whisper", "hello world", [{"start_s": 0, "end_s": 1, "text": "hello world"}])
    cached = store.get_transcript("g1")
    assert cached["text"] == "hello world"
    assert cached["provider"] == "whisper"


def test_signal_ledger_similarity(store):
    seg = Segment(item_guid="g1", start_s=0, end_s=10, text="agentic coding benchmark")
    sig = Signal(
        id="s1", item_guid="g1", theme_id="sdlc-inner-loop", segment=seg,
        final=0.8, embedding=[1.0, 0.0, 0.0],
    )
    store.add_signal(sig)
    # identical embedding -> similarity ~1.0
    assert store.max_similarity("sdlc-inner-loop", [1.0, 0.0, 0.0]) > 0.99
    # orthogonal -> ~0
    assert store.max_similarity("sdlc-inner-loop", [0.0, 1.0, 0.0]) < 0.01
    # different theme -> no prior
    assert store.max_similarity("pdlc-ai", [1.0, 0.0, 0.0]) == 0.0


def test_run_brief_sent_flag(store):
    store.start_run("r1")
    assert not store.run_brief_sent("r1")
    store.finish_run("r1", "delivered", brief_sent=True)
    assert store.run_brief_sent("r1")
