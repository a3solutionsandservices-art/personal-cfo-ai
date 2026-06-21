"""StaticContextProvider — the default, dependency-free provider (FR-CTX-1).

Reads portfolio context from ``portfolio.md`` and per-theme current state from
the taxonomy. Lets the system run with no external dependency. Any external
context/knowledge platform can replace it by implementing the same two methods.
"""

from __future__ import annotations

from pathlib import Path

from ..taxonomy import Taxonomy


class StaticContextProvider:
    def __init__(self, portfolio_path: str | Path, taxonomy: Taxonomy) -> None:
        self._portfolio_path = Path(portfolio_path)
        self._taxonomy = taxonomy
        self._cache: str | None = None

    def portfolio_context(self) -> str:
        if self._cache is None:
            if self._portfolio_path.exists():
                self._cache = self._portfolio_path.read_text(encoding="utf-8")
            else:
                self._cache = ""
        return self._cache

    def theme_state(self, theme_id: str) -> str:
        try:
            return self._taxonomy.by_id(theme_id).current_state
        except KeyError:
            return ""
