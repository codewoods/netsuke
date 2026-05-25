"""Bidirectional sRGB <-> CMYK conversion via Little CMS (PIL.ImageCms).

Customer workflow: they read CMYK values off an ISO 15339 / GRACoL CRPC
swatch chart on a printed proof and need the matching sRGB hex to drop
into HTML / Figma. We also serve the reverse direction so designers can
sanity-check what a chosen hex will print as under each ICC profile.

We use functools.lru_cache to memoise the lcms transform objects: each
build is ~10ms (file open + tag parse), and we expect repeated calls
hitting the same ICC during a picker session.
"""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageCms

CMYK = tuple[float, float, float, float]


def _normalize_hex(hx: str) -> str:
    """Accept #RGB, #RRGGBB, RGB, RRGGBB; return canonical lowercase #rrggbb.

    Why be lenient: customers paste from many sources (Figma, Slack,
    pasted CSS), and rejecting valid colors over a missing # is hostile.
    """
    s = hx.strip().lstrip("#").lower()
    if len(s) == 3 and all(c in "0123456789abcdef" for c in s):
        s = "".join(c * 2 for c in s)
    if len(s) != 6 or not all(c in "0123456789abcdef" for c in s):
        raise ValueError(f"invalid hex color: {hx!r}")
    return "#" + s


@lru_cache(maxsize=8)
def _forward(icc_path_str: str) -> ImageCms.ImageCmsTransform:
    """sRGB -> CMYK transform built once per ICC profile."""
    srgb = ImageCms.createProfile("sRGB")
    cmyk = ImageCms.getOpenProfile(icc_path_str)
    return ImageCms.buildTransform(srgb, cmyk, "RGB", "CMYK")


@lru_cache(maxsize=8)
def _reverse(icc_path_str: str) -> ImageCms.ImageCmsTransform:
    """CMYK -> sRGB transform built once per ICC profile."""
    srgb = ImageCms.createProfile("sRGB")
    cmyk = ImageCms.getOpenProfile(icc_path_str)
    return ImageCms.buildTransform(cmyk, srgb, "CMYK", "RGB")


def hex_to_cmyk(hex_color: str, icc_path: Path) -> CMYK:
    """Convert sRGB hex to CMYK percentages under the given ICC profile.

    We transform a 1x1 image so lcms handles the colorimetry consistently
    with how it would treat a full image; doing the math by hand would
    ignore the profile's gamut compression and rendering intent.
    """
    canon = _normalize_hex(hex_color)
    r, g, b = int(canon[1:3], 16), int(canon[3:5], 16), int(canon[5:7], 16)
    img = Image.new("RGB", (1, 1), (r, g, b))
    out = ImageCms.applyTransform(img, _forward(str(icc_path)))
    cv, mv, yv, kv = out.getpixel((0, 0))
    return (cv / 255 * 100, mv / 255 * 100, yv / 255 * 100, kv / 255 * 100)


def cmyk_to_hex(cmyk: CMYK, icc_path: Path) -> str:
    """Convert CMYK percentages (0-100) to sRGB hex via reverse lcms transform.

    The result is the *screen preview* of that ink combination — not a
    guarantee of what the press will produce, but the best approximation
    given the chosen profile.
    """
    if not all(0 <= v <= 100 for v in cmyk):
        raise ValueError(f"cmyk values must be 0-100: {cmyk}")
    cv, mv, yv, kv = (round(v / 100 * 255) for v in cmyk)
    img = Image.new("CMYK", (1, 1), (cv, mv, yv, kv))
    out = ImageCms.applyTransform(img, _reverse(str(icc_path)))
    r, g, b = out.getpixel((0, 0))
    return f"#{r:02x}{g:02x}{b:02x}"
