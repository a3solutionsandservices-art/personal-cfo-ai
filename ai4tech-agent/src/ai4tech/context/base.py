"""ContextProvider interface (PRD §7).

Supplies the lead's portfolio context to the Interpreter and theme state to the
Scorer. The interface is deliberately narrow (two methods) so any external
context or knowledge platform can back it later by implementing the same
contract — swapping providers is a config change with no downstream edits
(FR-CTX-2). The pipeline never blocks on an external source; an unavailable
provider falls back to static context (FR-CTX-3).
"""

from __future__ import annotations

from typing import Protocol


class ContextProvider(Protocol):  # pragma: no cover - structural
    def portfolio_context(self) -> str:
        """Mandate + remit summary for the Interpreter."""
        ...

    def theme_state(self, theme_id: str) -> str:
        """Current state for the Scorer / Interpreter, by theme."""
        ...
