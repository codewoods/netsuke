"""Render the first page of a PDF to a raster image via Ghostscript.

pdf_to_png: RGB preview for the client-side colour-blind canvases.
pdf_to_cmyk_tiff: CMYK TIFF for server-side pixel ink sampling.
"""

import subprocess
from pathlib import Path

DEFAULT_GHOSTSCRIPT_TIMEOUT_SECONDS = 60


def pdf_to_png(
    input_pdf: Path,
    output_png: Path,
    dpi: int = 96,
    timeout_seconds: int = DEFAULT_GHOSTSCRIPT_TIMEOUT_SECONDS,
) -> None:
    """Rasterize page 1 to a PNG at the given DPI.

    Why -dFirstPage=-dLastPage=1: previewing every page would be wasted
    work for the typical single-page poster/leaflet workflow; the client
    only renders one canvas group anyway.

    Why -sDEVICE=png16m: 24-bit RGB output, no alpha, so the canvas
    upload is predictable for the daltonize JS that reads RGBA pixels.
    """
    cmd = [
        "gs",
        "-dBATCH",
        "-dNOPAUSE",
        "-dSAFER",
        "-dQUIET",
        f"--permit-file-read={input_pdf}",
        f"--permit-file-write={output_png}",
        "-sDEVICE=png16m",
        f"-r{dpi}",
        "-dFirstPage=1",
        "-dLastPage=1",
        f"-sOutputFile={output_png}",
        str(input_pdf),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=timeout_seconds)


def pdf_to_cmyk_tiff(
    input_pdf: Path,
    output_tiff: Path,
    dpi: int = 72,
    timeout_seconds: int = DEFAULT_GHOSTSCRIPT_TIMEOUT_SECONDS,
) -> None:
    """Rasterize page 1 to a 32-bit CMYK TIFF for pixel-level ink sampling.

    Why tiff32nc: 4 channels × 8 bits per pixel; PIL reads each pixel as
    (C, M, Y, K) in 0-255 so the caller divides by 2.55 to get percentages.

    Why ColorConversionStrategy=CMYK: forces any mixed-space PDF into a
    single DeviceCMYK space. A print-shop CMYK-only file passes through
    with negligible drift; any RGB elements convert via the sRGB profile
    that their source embedded rather than being left as RGB bytes.
    """
    cmd = [
        "gs",
        "-dBATCH",
        "-dNOPAUSE",
        "-dSAFER",
        "-dQUIET",
        f"--permit-file-read={input_pdf}",
        f"--permit-file-write={output_tiff}",
        "-sDEVICE=tiff32nc",
        f"-r{dpi}",
        "-dFirstPage=1",
        "-dLastPage=1",
        "-sColorConversionStrategy=CMYK",
        "-sProcessColorModel=DeviceCMYK",
        f"-sOutputFile={output_tiff}",
        str(input_pdf),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=timeout_seconds)
