"""Ghostscript wrapper: RGB PDF -> CMYK PDF using an ICC output profile.

Pure function — all state (paths) passed in; no globals, no caching.
Returns nothing; relies on `check=True` to surface gs failures as
CalledProcessError so callers can map to HTTP 500 / inspect stderr.

image_to_pdf provides the upstream half of the pipeline: raster images
(jpg/png/tif/webp) are wrapped losslessly into a single-page PDF so the
existing gs CMYK pass can be reused without a separate image code path.
"""

import subprocess
from pathlib import Path

import img2pdf

DEFAULT_GHOSTSCRIPT_TIMEOUT_SECONDS = 120
IMAGE_SUFFIXES: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
)


def image_to_pdf(input_image: Path, output_pdf: Path) -> None:
    """Wrap a raster image into a single-page PDF using img2pdf.

    Why img2pdf vs Pillow.save("PDF"): img2pdf embeds JPEGs without
    re-encoding (lossless passthrough) and preserves the source DPI when
    available, which matters for print output where pixel dimensions
    drive physical size on the page.
    """
    with output_pdf.open("wb") as f:
        f.write(img2pdf.convert(str(input_image)))


def rgb_pdf_to_cmyk(
    input_pdf: Path,
    output_pdf: Path,
    icc_path: Path,
    timeout_seconds: int = DEFAULT_GHOSTSCRIPT_TIMEOUT_SECONDS,
) -> None:
    """Convert an RGB PDF to a CMYK PDF tagged with the given ICC profile.

    Why -dOverrideICC=true: Chrome's print-to-PDF embeds an sRGB profile,
    and without override gs would keep treating the document as sRGB.
    We want our destination ICC to win.

    Why -sColorConversionStrategy=CMYK + ColorConversionStrategyForImages:
    pdfwrite respects per-element strategies. Setting both forces all
    text/vectors AND raster images into DeviceCMYK; otherwise images
    can retain their source color space.

    Why -dPDFSETTINGS=/prepress: enables 300dpi image downsampling,
    embedded fonts, and other defaults that match a print-ready PDF
    rather than the gs default "screen" preset.

    Why --permit-file-read / --permit-file-write: gs 10 defaults to
    SAFER mode, which blocks file access outside the input PDF's
    directory. We must explicitly grant access to the ICC profile and
    the chosen output path. We keep SAFER on so a malicious PDF still
    can't reach the rest of the filesystem.
    """
    cmd = [
        "gs",
        "-dBATCH",
        "-dNOPAUSE",
        "-dSAFER",
        "-dQUIET",
        f"--permit-file-read={icc_path}",
        f"--permit-file-read={input_pdf}",
        f"--permit-file-write={output_pdf}",
        "-sDEVICE=pdfwrite",
        "-dPDFSETTINGS=/prepress",
        "-sProcessColorModel=DeviceCMYK",
        "-sColorConversionStrategy=CMYK",
        "-sColorConversionStrategyForImages=CMYK",
        "-dOverrideICC=true",
        f"-sOutputICCProfile={icc_path}",
        "-dRenderIntent=0",
        f"-sOutputFile={output_pdf}",
        str(input_pdf),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=timeout_seconds)
