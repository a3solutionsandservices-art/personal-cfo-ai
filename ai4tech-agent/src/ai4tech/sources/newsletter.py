"""NewsletterAdapter — second source type, proving the abstraction (M6 / G5).

A newsletter item is already text, so it carries its body in ``SourceItem.text``
and leaves ``audio_url`` empty. The Transcriber stage detects the pre-supplied
text and skips transcription entirely — no downstream stage changes. This is the
concrete demonstration that adding a source type is a one-milestone change.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from ..config import FeedConfig
from ..models import SourceItem


class NewsletterAdapter:
    def __init__(self, feed: FeedConfig) -> None:
        self.feed = feed

    def fetch_new(self) -> list[SourceItem]:
        import feedparser  # lazy import

        parsed = feedparser.parse(self.feed.url)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.feed.lookback_days)
        items: list[SourceItem] = []
        for entry in parsed.entries:
            published = _published(entry)
            if published and published < cutoff:
                continue
            body = _body(entry)
            if not body:
                continue
            guid = getattr(entry, "id", None) or getattr(entry, "link", entry.get("title", ""))
            items.append(
                SourceItem(
                    guid=str(guid),
                    source_id=self.feed.id,
                    title=getattr(entry, "title", "(untitled)"),
                    audio_url="",
                    published_at=published.isoformat() if published else "",
                    show=self.feed.show,
                    text=body,
                )
            )
        return items


def _body(entry) -> str:
    if getattr(entry, "content", None):
        return _strip_html(entry.content[0].get("value", ""))
    return _strip_html(getattr(entry, "summary", ""))


def _strip_html(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", " ", html).strip()


def _published(entry) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed is None:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)
