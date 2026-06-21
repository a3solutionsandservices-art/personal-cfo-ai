"""Source adapters. New source types drop in here without downstream changes (G5)."""

from .base import SourceAdapter, make_adapter
from .podcast import PodcastAdapter
from .newsletter import NewsletterAdapter

__all__ = ["SourceAdapter", "PodcastAdapter", "NewsletterAdapter", "make_adapter"]
