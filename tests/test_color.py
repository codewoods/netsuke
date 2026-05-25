"""Spec for color.py: bidirectional sRGB <-> CMYK via the bundled ICC.

Both directions go through PIL.ImageCms / lcms, so the round trip is
not exactly identity (printer gamut is smaller than sRGB), but values
should stay close for in-gamut colors. We assert each channel within
a tolerance rather than equality.
"""

from pathlib import Path

import pytest

from app.color import cmyk_to_hex, hex_to_cmyk

ICC_DIR = Path(__file__).parent.parent / "icc"
JAPAN_COATED = ICC_DIR / "JapanColor2011Coated.icc"


pytestmark = pytest.mark.skipif(
    not JAPAN_COATED.exists(), reason="ICC profile not yet copied"
)


def test_hex_to_cmyk_pure_red():
    """Pure sRGB red maps to high M+Y, low C, low K in coated profile."""
    c, m, y, k = hex_to_cmyk("#FF0000", JAPAN_COATED)
    assert all(0 <= v <= 100 for v in (c, m, y, k))
    assert m > 70 and y > 70, f"red should be M-heavy + Y-heavy: {(c, m, y, k)}"
    assert c < 30, f"red should have low C: c={c}"


def test_cmyk_to_hex_pure_black():
    """100% K (process black) should map near #000000 in sRGB preview."""
    hx = cmyk_to_hex((0, 0, 0, 100), JAPAN_COATED)
    assert hx.startswith("#") and len(hx) == 7
    r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
    # Coated black on screen is dark but not literally zero (paper white tone).
    assert max(r, g, b) < 80, f"black should be dark: {hx}"


def test_hex_normalizes_short_form():
    """3-digit hex (#F00) should expand and behave like 6-digit."""
    a = hex_to_cmyk("#F00", JAPAN_COATED)
    b = hex_to_cmyk("#FF0000", JAPAN_COATED)
    assert a == b


def test_hex_to_cmyk_rejects_garbage():
    with pytest.raises(ValueError):
        hex_to_cmyk("not-a-color", JAPAN_COATED)


def test_cmyk_to_hex_rejects_out_of_range():
    with pytest.raises(ValueError):
        cmyk_to_hex((0, 0, 0, 150), JAPAN_COATED)


def test_round_trip_in_gamut_color():
    """A clearly in-gamut blue: hex -> cmyk -> hex should stay close.

    Tolerance is generous because the printer profile's gamut is smaller
    than sRGB; the reverse transform clips out-of-gamut values.
    """
    src = "#3366CC"
    cmyk = hex_to_cmyk(src, JAPAN_COATED)
    back = cmyk_to_hex(cmyk, JAPAN_COATED)
    sr, sg, sb = int(src[1:3], 16), int(src[3:5], 16), int(src[5:7], 16)
    br, bg, bb = int(back[1:3], 16), int(back[3:5], 16), int(back[5:7], 16)
    assert abs(sr - br) < 35 and abs(sg - bg) < 35 and abs(sb - bb) < 35, (
        f"round trip drift too large: {src} -> {cmyk} -> {back}"
    )
