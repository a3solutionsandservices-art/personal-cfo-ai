"""Theme taxonomy loading and access (PRD §5, FR-TAX-1..4).

The taxonomy is the keystone artifact: the Classifier and Scorer use each
theme's ``signal_definition`` as their contract, ``weight`` scales the final
score, and ``current_state`` feeds the Scorer's novelty judgement and the
Interpreter's action drafting. A malformed file fails fast with a clear error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class TaxonomyError(ValueError):
    """Raised when the taxonomy file is missing or malformed (FR-TAX-1)."""


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    signal_definition: str
    action_templates: list[str]
    weight: float
    description: str = ""
    current_state: str = ""


@dataclass(frozen=True)
class Taxonomy:
    themes: list[Theme]

    def __post_init__(self) -> None:
        ids = [t.id for t in self.themes]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise TaxonomyError(f"duplicate theme ids: {sorted(dupes)}")

    def by_id(self, theme_id: str) -> Theme:
        for t in self.themes:
            if t.id == theme_id:
                return t
        raise KeyError(theme_id)

    @property
    def ids(self) -> list[str]:
        return [t.id for t in self.themes]


def load_taxonomy(path: str | Path) -> Taxonomy:
    """Load and validate the taxonomy YAML (FR-TAX-1).

    Each theme inherits ``defaults`` for any of ``signal_definition``,
    ``action_templates``, ``weight`` it omits (PRD §5 footnote).
    """
    p = Path(path)
    if not p.exists():
        raise TaxonomyError(f"taxonomy file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:  # pragma: no cover - exercised via tests
        raise TaxonomyError(f"taxonomy YAML is malformed: {e}") from e

    if not isinstance(raw, dict) or "themes" not in raw:
        raise TaxonomyError("taxonomy must be a mapping with a 'themes' key")

    defaults = raw.get("defaults") or {}
    themes: list[Theme] = []
    for i, entry in enumerate(raw["themes"]):
        if not isinstance(entry, dict):
            raise TaxonomyError(f"theme #{i} is not a mapping")
        if "id" not in entry or "name" not in entry:
            raise TaxonomyError(f"theme #{i} missing required 'id'/'name'")

        signal_definition = _clean(
            entry.get("signal_definition", defaults.get("signal_definition", ""))
        )
        if not signal_definition:
            raise TaxonomyError(
                f"theme '{entry['id']}' has no signal_definition and no default "
                "(FR-TAX-2: signal_definition is the classifier/scorer contract)"
            )

        templates = entry.get("action_templates", defaults.get("action_templates", []))
        if not templates:
            raise TaxonomyError(f"theme '{entry['id']}' has no action_templates")

        weight = float(entry.get("weight", defaults.get("weight", 1.0)))
        if not 0.0 <= weight <= 1.0:
            raise TaxonomyError(
                f"theme '{entry['id']}' weight {weight} out of range [0,1] (FR-TAX-3)"
            )

        themes.append(
            Theme(
                id=str(entry["id"]),
                name=str(entry["name"]),
                signal_definition=signal_definition,
                action_templates=list(templates),
                weight=weight,
                description=_clean(entry.get("description", "")),
                current_state=_clean(entry.get("current_state", "")),
            )
        )

    if not themes:
        raise TaxonomyError("taxonomy contains no themes")
    return Taxonomy(themes=themes)


def _clean(text: str) -> str:
    """Collapse the whitespace YAML block scalars introduce."""
    return " ".join(str(text).split())
