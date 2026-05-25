# ICC Profile Notices

All profiles in this directory were obtained from
[registry.color.org](https://registry.color.org/profile-registry/) and
are redistributed here under terms that permit use, embedding, exchange,
and sharing without restriction. None of them may be altered or sold
without written permission of the listed steward.

| File                                 | Steward            | Owner    | Source URL |
|--------------------------------------|--------------------|----------|------------|
| `JapanColor2011Coated.icc`           | JPMA               | X-Rite   | https://registry.color.org/profile-registry/profiles/JapanColor2011Coated.icc |
| `Coated_Fogra39L_VIGC_300.icc`       | VIGC               | X-Rite   | https://registry.color.org/profile-registry/profiles/Coated_Fogra39L_VIGC_300.icc |
| `GRACoL2006_Coated1v2.icc`           | Idealliance        | X-Rite   | https://registry.color.org/profile-registry/profiles/GRACoL2006_Coated1v2.icc |
| `SWOP2006_Coated3v2.icc`             | Idealliance        | X-Rite   | https://registry.color.org/profile-registry/profiles/SWOP2006_Coated3v2.icc |
| `SWOP2006_Coated5v2.icc`             | Idealliance        | X-Rite   | https://registry.color.org/profile-registry/profiles/SWOP2006_Coated5v2.icc |
| `Uncoated_Fogra47L_VIGC_300.icc`     | VIGC               | X-Rite   | https://registry.color.org/profile-registry/profiles/Uncoated_Fogra47L_VIGC_300.icc |

Each profile's embedded `cprt` tag carries its own copyright string;
extract with e.g. `iccdump -v3 -t cprt <file>.icc` or any ICC profile
inspector.

## Verbatim copyright text (representative)

> This profile is made available by *<steward>*, with permission of
> X-Rite, Incorporated, and may be used, embedded, exchanged, and shared
> without restriction. It may not be altered or sold without written
> permission of *<steward>*.

## Adding your own profile

This service expects the file to live directly under `icc/` and to be
registered in `app/icc_catalog.py` (immutable tuple `CATALOG`, plus
`DEFAULTS` if it should be the region default for its paper type).

Newspaper stock is intentionally not bundled: WAN-IFRA distributes the
public ISOnewspaper26v4 / 26v5 profile only through a Google Drive
gate, which we cannot script. To enable newspaper output, drop the ICC
into `icc/`, add the entry to the catalog with `paper="newspaper"`,
and re-add the `newspaper` member to the `PaperType` Literal.
