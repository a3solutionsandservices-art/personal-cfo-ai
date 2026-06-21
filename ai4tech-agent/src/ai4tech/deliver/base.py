"""Delivery stage (PRD §6.8).

The Deliverer interface allows future Slack/Doc targets without pipeline changes
(FR-DEL-2). ``render_markdown`` is the shared brief renderer used by both the
markdown-file and email deliverers. Empty runs send a one-line "no signal this
period" rather than silence (FR-DEL-3).
"""

from __future__ import annotations

from typing import Protocol

from ..models import Brief


class Deliverer(Protocol):  # pragma: no cover - structural
    def deliver(self, brief: Brief) -> str:
        """Deliver the brief. Returns a human-readable description of where."""
        ...


def render_markdown(brief: Brief) -> str:
    """Render a Brief to markdown — scannable in under five minutes (G4)."""
    lines: list[str] = []
    lines.append("# AI4Tech Intelligence Brief")
    lines.append("")
    lines.append(f"_Run `{brief.run_id}` · generated {brief.generated_at}_")
    lines.append("")

    if not brief.actions:
        lines.append("**No signal this period.** Nothing cleared the relevance "
                     "threshold in the processed sources. (FR-DEL-3)")
        lines.append("")
        return "\n".join(lines)

    # Digest: one line per theme (FR-BRF-4).
    lines.append("## Digest")
    lines.append("")
    for d in brief.digest:
        lines.append(f"- {d.line}")
    lines.append("")

    # Ranked actions, grouped by theme as they are already ordered.
    lines.append("## Recommended actions")
    lines.append("")
    current_theme = None
    for i, a in enumerate(brief.actions, start=1):
        if a.theme_id != current_theme:
            current_theme = a.theme_id
            lines.append(f"### {_theme_label(brief, a.theme_id)}")
            lines.append("")
        lines.append(f"{i}. **[{a.action_type}]** {a.recommendation}  ")
        lines.append(f"   _Why:_ {a.rationale}  ")
        lines.append(
            f"   _Confidence:_ {a.confidence} · _Score:_ {a.final:.2f}  "
        )
        ts = _fmt_ts(a.citation.start_s)
        lines.append(
            f"   _Source:_ `{a.citation.item_guid}` @ {ts} — "
            f"\"{a.citation.excerpt.strip()}\""
        )
        lines.append("")

    if brief.also_noted:
        lines.append("## Also noted")
        lines.append("")
        for note in brief.also_noted:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)


def _theme_label(brief: Brief, theme_id: str) -> str:
    for d in brief.digest:
        if d.theme_id == theme_id:
            # digest line starts with the theme name up to the first colon
            return d.line.split(":", 1)[0]
    return theme_id


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def make_deliverer(delivery: dict) -> Deliverer:
    """Select the deliverer from config (FR-DEL-1)."""
    from .email import EmailDeliverer
    from .markdown import MarkdownDeliverer

    target = delivery.get("target", "markdown")
    if target == "email":
        return EmailDeliverer(delivery.get("email", {}))
    return MarkdownDeliverer(delivery.get("output_dir", "./out"))
