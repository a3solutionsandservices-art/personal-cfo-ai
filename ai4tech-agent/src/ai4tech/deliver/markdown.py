"""Markdown-file deliverer — the default target (FR-DEL-1)."""

from __future__ import annotations

from pathlib import Path

from ..models import Brief
from .base import render_markdown


class MarkdownDeliverer:
    def __init__(self, output_dir: str | Path = "./out") -> None:
        self.output_dir = Path(output_dir)

    def deliver(self, brief: Brief) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"brief-{brief.run_id}.md"
        path.write_text(render_markdown(brief), encoding="utf-8")
        return str(path)
