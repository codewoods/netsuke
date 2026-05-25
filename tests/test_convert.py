"""Spec for convert.rgb_pdf_to_cmyk and convert.image_to_pdf.

End-to-end ghostscript invocation: build a tiny RGB PDF with gs itself
(red square via PostScript), convert it, then verify the output is in
DeviceCMYK by inspecting per-page ink coverage with -sDEVICE=inkcov.

The inkcov device prints `C M Y K CMYK OK` rows — if conversion worked,
at least one of C/M/Y/K must be non-zero. A pure-RGB output would yield
an empty/zero inkcov result.
"""

import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from app.convert import image_to_pdf, rgb_pdf_to_cmyk

ICC_DIR = Path(__file__).parent.parent / "icc"
JAPAN_COATED = ICC_DIR / "JapanColor2011Coated.icc"


def _make_rgb_pdf(path: Path) -> None:
    """Generate a 1-page PDF with a red rectangle (pure RGB source)."""
    ps = (
        "%!PS-Adobe-3.0\n"
        "/setcolor { setrgbcolor } def\n"
        "0.9 0.2 0.2 setcolor\n"
        "72 72 200 100 rectfill\n"
        "showpage\n"
    )
    ps_path = path.with_suffix(".ps")
    ps_path.write_text(ps)
    subprocess.run(
        [
            "gs", "-dBATCH", "-dNOPAUSE", "-dQUIET",
            "-sDEVICE=pdfwrite",
            "-sProcessColorModel=DeviceRGB",
            "-sColorConversionStrategy=RGB",
            f"-sOutputFile={path}",
            str(ps_path),
        ],
        check=True,
        capture_output=True,
    )


def _inkcov(pdf: Path) -> str:
    """Run gs inkcov device; returns CMYK coverage report stdout."""
    result = subprocess.run(
        [
            "gs", "-dBATCH", "-dNOPAUSE", "-dQUIET",
            "-sDEVICE=inkcov",
            "-o", "-",
            str(pdf),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


@pytest.mark.skipif(not JAPAN_COATED.exists(), reason="ICC profile not yet copied")
def test_converts_rgb_pdf_to_cmyk(tmp_path: Path) -> None:
    src = tmp_path / "src.pdf"
    dst = tmp_path / "dst_cmyk.pdf"
    _make_rgb_pdf(src)

    rgb_pdf_to_cmyk(src, dst, JAPAN_COATED)

    assert dst.exists()
    assert dst.stat().st_size > 0

    coverage = _inkcov(dst)
    # inkcov rows look like: "0.12345  0.04321  0.00000  0.00000 CMYK OK"
    lines = [l for l in coverage.splitlines() if "CMYK OK" in l]
    assert lines, f"no CMYK ink coverage rows in:\n{coverage}"
    values = [float(x) for x in lines[0].split()[:4]]
    assert any(v > 0 for v in values), f"all CMYK channels zero: {values}"


def test_rgb_pdf_to_cmyk_uses_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ghostscript invocations must be bounded to avoid stuck conversions."""
    calls: list[dict] = []

    def fake_run(_cmd: list[str], **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(_cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    rgb_pdf_to_cmyk(tmp_path / "in.pdf", tmp_path / "out.pdf", tmp_path / "x.icc")
    assert calls and calls[0]["timeout"] > 0


def _make_png(path: Path, width: int = 8, height: int = 8) -> None:
    """Build a minimal opaque red PNG using only stdlib (zlib + struct).

    Why hand-rolled: keeps the test free of Pillow/img2pdf at the spec
    layer — the production code uses img2pdf, but a spec for the helper
    only needs *some* valid PNG bytes on disk to exercise the wrapping.
    """
    raw = b""
    for _ in range(height):
        raw += b"\x00"  # PNG filter byte (None) per scanline
        raw += b"\xe6\x33\x33" * width  # solid red pixels
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunks = [
        (b"IHDR", ihdr),
        (b"IDAT", zlib.compress(raw, 9)),
        (b"IEND", b""),
    ]
    out = b"\x89PNG\r\n\x1a\n"
    for tag, data in chunks:
        out += struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.write_bytes(out)


def test_image_to_pdf_wraps_png(tmp_path: Path) -> None:
    """image_to_pdf should produce a valid PDF byte stream for a PNG input."""
    img = tmp_path / "red.png"
    _make_png(img)
    out = tmp_path / "wrapped.pdf"
    image_to_pdf(img, out)
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF-")


@pytest.mark.skipif(not JAPAN_COATED.exists(), reason="ICC profile not yet copied")
def test_image_to_pdf_then_cmyk(tmp_path: Path) -> None:
    """End-to-end: PNG -> wrapped PDF -> CMYK PDF with non-zero ink coverage."""
    img = tmp_path / "red.png"
    _make_png(img, width=64, height=64)
    wrapped = tmp_path / "wrapped.pdf"
    image_to_pdf(img, wrapped)
    cmyk = tmp_path / "cmyk.pdf"
    rgb_pdf_to_cmyk(wrapped, cmyk, JAPAN_COATED)
    coverage = _inkcov(cmyk)
    rows = [l for l in coverage.splitlines() if "CMYK OK" in l]
    assert rows, f"no CMYK rows in:\n{coverage}"
    values = [float(x) for x in rows[0].split()[:4]]
    assert any(v > 0 for v in values), f"all CMYK channels zero: {values}"


@pytest.mark.skipif(not JAPAN_COATED.exists(), reason="ICC profile not yet copied")
def test_raises_on_invalid_input(tmp_path: Path) -> None:
    src = tmp_path / "not_a.pdf"
    src.write_text("this is not a PDF")
    dst = tmp_path / "dst.pdf"
    with pytest.raises(subprocess.CalledProcessError):
        rgb_pdf_to_cmyk(src, dst, JAPAN_COATED)
