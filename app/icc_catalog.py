"""Pure-functional ICC profile taxonomy.

Single source of truth for the CMYK ICC profiles bundled with the
service. All entries are sourced from registry.color.org or other
permissively-licensed origins so this repo can be published publicly.

Default selection follows Adobe InDesign region presets for zh-TW /
ja-JP: Japan Color 2011 Coated (the JPMA/X-Rite successor to the
2001 series) is the coated-stock default.

Provenance / license per file:
    JapanColor2011Coated.icc        JPMA / X-Rite — "use, embed,
                                    exchange, share without restriction;
                                    may not be altered or sold w/o
                                    written permission of X-Rite".
    GRACoL2006_Coated1v2.icc        IDEAlliance / X-Rite — same terms.
    Coated_Fogra39L_VIGC_300.icc    VIGC / X-Rite — same terms.
    SWOP2006_Coated3v2.icc          IDEAlliance / X-Rite — same terms.
    SWOP2006_Coated5v2.icc          IDEAlliance / X-Rite — same terms.
    Uncoated_Fogra47L_VIGC_300.icc  VIGC / X-Rite — same terms.

Newspaper stock is intentionally omitted: WAN-IFRA distributes the
public newspaper profile (ISOnewspaper26v4 / 26v5) only through a
Google Drive gate that we cannot script, and there is no permissively-
licensed mirror. Users who need newspaper output should drop their
own ICC into icc/ and extend CATALOG below.
"""

from dataclasses import dataclass
from typing import Literal

PaperType = Literal["coated", "uncoated"]


@dataclass(frozen=True)
class ICCProfile:
    filename: str
    display: str
    paper: PaperType
    region: str  # "JP/TW", "EU", "US"


# Ordering inside each paper bucket is intentional: the region-default
# profile comes first so a naive "pick the head" still does the right
# thing if DEFAULTS is unavailable.
CATALOG: tuple[ICCProfile, ...] = (
    ICCProfile(
        "JapanColor2011Coated.icc",
        "Japan Color 2011 Coated",
        "coated",
        "JP/TW",
    ),
    ICCProfile(
        "Coated_Fogra39L_VIGC_300.icc",
        "Coated FOGRA39L (VIGC, TAC 300%)",
        "coated",
        "EU",
    ),
    ICCProfile(
        "GRACoL2006_Coated1v2.icc",
        "GRACoL 2006 Coated #1 v2",
        "coated",
        "US",
    ),
    ICCProfile(
        "SWOP2006_Coated3v2.icc",
        "SWOP 2006 Coated #3 v2 (Web)",
        "coated",
        "US",
    ),
    ICCProfile(
        "SWOP2006_Coated5v2.icc",
        "SWOP 2006 Coated #5 v2 (Web)",
        "coated",
        "US",
    ),
    ICCProfile(
        "Uncoated_Fogra47L_VIGC_300.icc",
        "Uncoated FOGRA47L (VIGC, TAC 300%)",
        "uncoated",
        "EU",
    ),
)

# Region default per paper type. Mirrors Adobe InDesign zh-TW / ja-JP
# presets for coated; uncoated has only one bundled option.
DEFAULTS: dict[PaperType, str] = {
    "coated": "JapanColor2011Coated.icc",
    "uncoated": "Uncoated_Fogra47L_VIGC_300.icc",
}

PAPER_LABELS: dict[PaperType, str] = {
    "coated": "銅版紙 Coated",
    "uncoated": "道林紙 Uncoated",
}


def filter_by_paper(paper: PaperType) -> tuple[ICCProfile, ...]:
    """Return profiles matching the given paper type, preserving order."""
    return tuple(p for p in CATALOG if p.paper == paper)


def allowed_filenames() -> frozenset[str]:
    """Whitelist used by the upload handler to reject path traversal."""
    return frozenset(p.filename for p in CATALOG)


def get_profile(filename: str) -> ICCProfile | None:
    """Lookup by filename; returns None if not in catalog."""
    return next((p for p in CATALOG if p.filename == filename), None)
