"""PodcastAdapter — polls an RSS feed and yields new episodes (FR-SRC-1).

Yields a SourceItem per episode (title, audio enclosure URL, publish date,
show, GUID). The pipeline filters out GUIDs already in the StateStore, so this
adapter only needs to surface the feed contents; it does not track state.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from ..config import FeedConfig
from ..models import SourceItem


class PodcastAdapter:
    def __init__(self, feed: FeedConfig) -> None:
        self.feed = feed

    def fetch_new(self) -> list[SourceItem]:
        import feedparser  # lazy import; only the podcast path needs it

        parsed = feedparser.parse(self.feed.url)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.feed.lookback_days)
        items: list[SourceItem] = []
        for entry in parsed.entries:
            audio_url = _enclosure_url(entry)
            if not audio_url:
                continue
            published = _published(entry)
            if published and published < cutoff:
                continue
            guid = getattr(entry, "id", None) or audio_url
            items.append(
                SourceItem(
                    guid=str(guid),
                    source_id=self.feed.id,
                    title=getattr(entry, "title", "(untitled)"),
                    audio_url=audio_url,
                    published_at=published.isoformat() if published else "",
                    show=self.feed.show,
                )
            )
        return items


def _enclosure_url(entry) -> str:
    for enc in getattr(entry, "enclosures", []) or []:
        href = enc.get("href") or enc.get("url")
        if href:
            return href
    for link in getattr(entry, "links", []) or []:
        if link.get("rel") == "enclosure" and link.get("href"):
            return link["href"]
    return ""


def _published(entry) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed is None:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)
