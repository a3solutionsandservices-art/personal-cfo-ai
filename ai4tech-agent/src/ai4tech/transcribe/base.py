"""Transcription stage (PRD §6.2).

STT is a commodity behind an adapter (non-goal: building an STT engine). The
``CachingTranscriber`` wraps any backend and:

  * returns text directly for already-textual items (newsletters) — no STT;
  * serves a cached transcript by GUID on re-runs (FR-TR-4, cost control);
  * otherwise calls the backend and caches the result.

Backends produce word/segment-level timestamps to support traceability (G3)
and segmentation (FR-TR-2). Diarization is captured when available but never
blocks the pipeline (FR-TR-3).
"""

from __future__ import annotations

from typing import Protocol

from ..models import SourceItem, Transcript
from ..state import StateStore


class Transcriber(Protocol):  # pragma: no cover - structural
    def transcribe(self, item: SourceItem) -> Transcript: ...


class WhisperTranscriber:
    """Default STT backend (PRD §10): Whisper via the OpenAI-compatible API.

    Downloads the audio enclosure and submits it. Requires the audio to be
    reachable and an API key; selected by ``transcription.provider``.
    """

    def __init__(self, model: str = "whisper-1", client=None) -> None:
        self.model = model
        self._client = client

    def transcribe(self, item: SourceItem) -> Transcript:  # pragma: no cover - network
        import tempfile
        import urllib.request

        if self._client is None:
            import openai

            self._client = openai.OpenAI()

        with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
            urllib.request.urlretrieve(item.audio_url, tmp.name)
            with open(tmp.name, "rb") as fh:
                resp = self._client.audio.transcriptions.create(
                    model=self.model, file=fh, response_format="verbose_json"
                )
        segments = [
            {
                "start_s": float(getattr(s, "start", 0.0)),
                "end_s": float(getattr(s, "end", 0.0)),
                "text": getattr(s, "text", "").strip(),
                "speaker": None,
            }
            for s in getattr(resp, "segments", []) or []
        ]
        return Transcript(
            item_guid=item.guid,
            text=getattr(resp, "text", ""),
            segments=segments,
            provider="whisper",
        )


class NullTranscriber:
    """No-op backend used when audio STT is unavailable (offline/dry-run).

    Textual items still transcribe (handled by CachingTranscriber); audio items
    yield an empty transcript that the pipeline quarantines rather than crashing.
    """

    def transcribe(self, item: SourceItem) -> Transcript:
        return Transcript(item_guid=item.guid, text="", segments=[], provider="null")


class CachingTranscriber:
    """Wrap a backend with text short-circuit + GUID cache (FR-TR-4)."""

    def __init__(self, backend: Transcriber, store: StateStore) -> None:
        self.backend = backend
        self.store = store

    def transcribe(self, item: SourceItem) -> Transcript:
        # Already-textual source (e.g. newsletter): no STT needed (G5).
        if item.text:
            return Transcript(
                item_guid=item.guid,
                text=item.text,
                segments=[{"start_s": 0.0, "end_s": 0.0, "text": item.text, "speaker": None}],
                provider="text",
            )

        cached = self.store.get_transcript(item.guid)
        if cached is not None:
            return Transcript(
                item_guid=item.guid,
                text=cached["text"],
                segments=cached["segments"],
                provider=cached.get("provider", "cache"),
            )

        transcript = self.backend.transcribe(item)
        if transcript.text:
            self.store.put_transcript(
                item.guid, transcript.provider, transcript.text, transcript.segments
            )
        return transcript


def make_transcriber(transcription: dict, store: StateStore) -> CachingTranscriber:
    """Select the STT backend from config and wrap it with caching."""
    import os

    provider = transcription.get("provider", "whisper")
    backend: Transcriber
    if provider == "whisper" and os.environ.get("OPENAI_API_KEY"):
        backend = WhisperTranscriber(model=transcription.get("whisper_model", "whisper-1"))
    else:
        # Deepgram/AssemblyAI would be constructed here when configured.
        backend = NullTranscriber()
    return CachingTranscriber(backend, store)
