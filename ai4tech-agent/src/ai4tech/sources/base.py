"""SourceAdapter interface (PRD §6.1, FR-SRC-3).

Every source type implements the same narrow interface so that newsletter /
arXiv / release-note adapters drop in later with no downstream changes (G5).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config import FeedConfig
from ..models import SourceItem


@runtime_checkable
class SourceAdapter(Protocol):
    feed: FeedConfig

    def fetch_new(self) -> list[SourceItem]:
        """Return new items from the feed (caller filters already-seen GUIDs)."""
        ...


def make_adapter(feed: FeedConfig) -> SourceAdapter:
    """Construct the adapter for a feed's declared type (FR-SRC-4)."""
    from .podcast import PodcastAdapter
    from .newsletter import NewsletterAdapter

    if feed.type == "podcast":
        return PodcastAdapter(feed)
    if feed.type == "newsletter":
        return NewsletterAdapter(feed)
    raise ValueError(f"unknown source type '{feed.type}' for feed '{feed.id}'")
