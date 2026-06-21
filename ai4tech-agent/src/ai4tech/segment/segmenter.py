"""Segmentation stage (PRD §6.3).

Splits a transcript into topic-coherent segments of roughly a few hundred words
(~1-4 minutes), not fixed-length chunks, and preserves each segment's start/end
timestamps and source item reference (FR-SEG-1/2) so downstream actions can cite
a real transcript span (G3).

The grouping heuristic accumulates timestamped transcript segments until the
target word count is reached, preferring to break on a pause/speaker change.
"""

from __future__ import annotations

from ..models import Segment, Transcript


class Segmenter:
    def __init__(self, target_words: int = 220, min_words: int = 60) -> None:
        self.target_words = target_words
        self.min_words = min_words

    def segment(self, transcript: Transcript) -> list[Segment]:
        raw = transcript.segments
        if not raw:
            return []

        segments: list[Segment] = []
        buf: list[dict] = []
        words = 0

        def flush() -> None:
            nonlocal buf, words
            if not buf:
                return
            text = " ".join(s["text"] for s in buf).strip()
            if text:
                segments.append(
                    Segment(
                        item_guid=transcript.item_guid,
                        start_s=float(buf[0].get("start_s", 0.0)),
                        end_s=float(buf[-1].get("end_s", 0.0)),
                        text=text,
                        speaker=buf[0].get("speaker"),
                    )
                )
            buf = []
            words = 0

        prev_speaker = None
        for s in raw:
            n = len(s.get("text", "").split())
            speaker_change = (
                prev_speaker is not None
                and s.get("speaker") is not None
                and s.get("speaker") != prev_speaker
            )
            # Break on a speaker turn (keeps topics — and filler vs substance —
            # from bleeding together) or once we reach the target word count.
            if buf and (speaker_change or words >= self.target_words):
                flush()
            buf.append(s)
            words += n
            prev_speaker = s.get("speaker") or prev_speaker

        flush()

        # Merge a too-small trailing tail into the previous segment only when it
        # is the same speaker (never glue a fragment onto a different turn).
        if (
            len(segments) >= 2
            and len(segments[-1].text.split()) < self.min_words
            and segments[-1].speaker == segments[-2].speaker
        ):
            last = segments.pop()
            prev = segments.pop()
            segments.append(
                Segment(
                    item_guid=prev.item_guid,
                    start_s=prev.start_s,
                    end_s=last.end_s,
                    text=f"{prev.text} {last.text}",
                    speaker=prev.speaker,
                )
            )
        return segments
