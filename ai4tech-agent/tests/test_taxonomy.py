"""Taxonomy loading and validation (FR-TAX-1..4)."""

import pytest

from ai4tech.taxonomy import TaxonomyError, load_taxonomy


def test_loads_all_themes(config):
    tax = config.taxonomy
    assert len(tax.themes) == 9
    assert "sdlc-inner-loop" in tax.ids
    # weight in range (FR-TAX-3)
    for t in tax.themes:
        assert 0.0 <= t.weight <= 1.0
        assert t.signal_definition  # the classifier/scorer contract (FR-TAX-2)
        assert t.action_templates


def test_defaults_are_inherited(tmp_path):
    f = tmp_path / "themes.yaml"
    f.write_text(
        "defaults:\n"
        "  signal_definition: default def\n"
        "  action_templates: [evaluate]\n"
        "  weight: 0.5\n"
        "themes:\n"
        "  - id: t1\n"
        "    name: Theme One\n"
    )
    tax = load_taxonomy(f)
    assert tax.by_id("t1").signal_definition == "default def"
    assert tax.by_id("t1").weight == 0.5


def test_malformed_fails_fast(tmp_path):
    f = tmp_path / "themes.yaml"
    f.write_text(": : not valid yaml : :\n  - broken")
    with pytest.raises(TaxonomyError):
        load_taxonomy(f)


def test_missing_signal_definition_fails(tmp_path):
    f = tmp_path / "themes.yaml"
    f.write_text("themes:\n  - id: t1\n    name: One\n    action_templates: [x]\n")
    with pytest.raises(TaxonomyError):
        load_taxonomy(f)


def test_out_of_range_weight_fails(tmp_path):
    f = tmp_path / "themes.yaml"
    f.write_text(
        "themes:\n  - id: t1\n    name: One\n    signal_definition: d\n"
        "    action_templates: [x]\n    weight: 5\n"
    )
    with pytest.raises(TaxonomyError):
        load_taxonomy(f)
