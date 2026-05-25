"""Spec for icc_catalog: invariants over the static data table.

These tests pin down assumptions the UI and convert path rely on:
- every paper type has a default
- defaults point at real catalog entries
- filenames are unique (the upload whitelist depends on it)
- filter_by_paper preserves catalog order
"""

from app.icc_catalog import (
    CATALOG,
    DEFAULTS,
    PAPER_LABELS,
    allowed_filenames,
    filter_by_paper,
    get_profile,
)


def test_catalog_has_six_public_profiles():
    """Six redistributable profiles bundled from registry.color.org."""
    assert len(CATALOG) == 6


def test_filenames_unique():
    filenames = [p.filename for p in CATALOG]
    assert len(filenames) == len(set(filenames))


def test_defaults_reference_real_profiles():
    """DEFAULTS must point at entries that actually exist in CATALOG."""
    names = {p.filename for p in CATALOG}
    for paper, fname in DEFAULTS.items():
        assert fname in names, f"default {fname} for {paper} not in catalog"


def test_defaults_match_paper_bucket():
    """Each default must belong to the paper bucket that points at it."""
    for paper, fname in DEFAULTS.items():
        profile = get_profile(fname)
        assert profile is not None
        assert profile.paper == paper


def test_filter_by_paper_returns_only_matching():
    for paper in PAPER_LABELS:
        for profile in filter_by_paper(paper):
            assert profile.paper == paper


def test_filter_preserves_catalog_order():
    """UI relies on first-element-is-region-default — see catalog ordering."""
    coated = filter_by_paper("coated")
    assert coated[0].filename == "JapanColor2011Coated.icc"


def test_taiwan_indesign_default_is_japan_color_coated():
    assert DEFAULTS["coated"] == "JapanColor2011Coated.icc"


def test_allowed_filenames_matches_catalog():
    assert allowed_filenames() == frozenset(p.filename for p in CATALOG)


def test_get_profile_unknown_returns_none():
    assert get_profile("../etc/passwd") is None
    assert get_profile("Nonexistent.icc") is None
