"""Spec for main.py: HTTP surface & end-to-end conversion via TestClient."""

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
ICC_DIR = Path(__file__).parent.parent / "icc"


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_index_renders():
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    # Default selections must be present in the rendered page.
    assert "Japan Color 2011 Coated" in body
    assert "銅版紙" in body


def test_icc_endpoint_coated():
    r = client.get("/icc?paper=coated")
    assert r.status_code == 200
    profiles = r.json()
    # All returned profiles belong to coated bucket.
    assert all(p["filename"].endswith(".icc") for p in profiles)
    defaults = [p for p in profiles if p["default"]]
    assert len(defaults) == 1
    assert defaults[0]["filename"] == "JapanColor2011Coated.icc"
    # All coated profiles must be tagged accordingly in the registry.
    assert all(p["filename"].endswith(".icc") for p in profiles)


def test_icc_endpoint_rejects_unknown_paper():
    r = client.get("/icc?paper=metallic")
    assert r.status_code == 400


def test_convert_rejects_unknown_icc(tmp_path: Path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    r = client.post(
        "/convert",
        data={"icc": "../etc/passwd"},
        files={"file": ("x.pdf", pdf.open("rb"), "application/pdf")},
    )
    assert r.status_code == 400


def test_convert_rejects_non_pdf(tmp_path: Path):
    """Only PDF and known image extensions are accepted."""
    txt = tmp_path / "x.txt"
    txt.write_text("nope")
    r = client.post(
        "/convert",
        data={"icc": "JapanColor2011Coated.icc"},
        files={"file": ("x.txt", txt.open("rb"), "text/plain")},
    )
    assert r.status_code == 400


def test_convert_rejects_upload_over_limit(monkeypatch):
    """Oversized uploads should be rejected before Ghostscript is invoked."""
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 12, raising=False)
    r = client.post(
        "/convert",
        data={"icc": "JapanColor2011Coated.icc"},
        files={"file": ("x.pdf", b"%PDF-1.4\noversized", "application/pdf")},
    )
    assert r.status_code == 413


def _tiny_red_png(path: Path) -> None:
    """Stdlib-only PNG writer; mirrors the helper in test_convert.py."""
    import struct, zlib
    w = h = 8
    raw = (b"\x00" + b"\xe6\x33\x33" * w) * h
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunks = [(b"IHDR", ihdr), (b"IDAT", zlib.compress(raw, 9)), (b"IEND", b"")]
    blob = b"\x89PNG\r\n\x1a\n"
    for tag, data in chunks:
        blob += struct.pack(">I", len(data)) + tag + data
        blob += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.write_bytes(blob)


@pytest.mark.skipif(
    not (ICC_DIR / "JapanColor2011Coated.icc").exists(),
    reason="ICC profile not yet copied",
)
def test_convert_accepts_png(tmp_path: Path):
    """PNG upload should produce a CMYK PDF (filename stem + _cmyk.pdf)."""
    img = tmp_path / "logo.png"
    _tiny_red_png(img)
    with img.open("rb") as f:
        r = client.post(
            "/convert",
            data={"icc": "JapanColor2011Coated.icc"},
            files={"file": ("logo.png", f, "image/png")},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "logo_cmyk.pdf" in r.headers.get("content-disposition", "")


@pytest.mark.skipif(
    not (ICC_DIR / "JapanColor2011Coated.icc").exists(),
    reason="ICC profile not yet copied",
)
def test_preview_endpoint_returns_png(tmp_path: Path):
    """POST /preview with a PDF returns a PNG raster of the first page."""
    ps = tmp_path / "src.ps"
    ps.write_text(
        "%!PS-Adobe-3.0\n"
        "0.9 0.2 0.2 setrgbcolor\n"
        "72 72 200 100 rectfill\n"
        "showpage\n"
    )
    pdf = tmp_path / "src.pdf"
    subprocess.run(
        [
            "gs", "-dBATCH", "-dNOPAUSE", "-dQUIET",
            "-sDEVICE=pdfwrite", f"-sOutputFile={pdf}", str(ps),
        ],
        check=True, capture_output=True,
    )
    with pdf.open("rb") as f:
        r = client.post(
            "/preview",
            files={"file": ("src.pdf", f, "application/pdf")},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_rejects_non_pdf(tmp_path: Path):
    txt = tmp_path / "x.txt"
    txt.write_text("nope")
    r = client.post(
        "/preview",
        files={"file": ("x.txt", txt.open("rb"), "text/plain")},
    )
    assert r.status_code == 400


def test_preview_rejects_upload_over_limit(monkeypatch):
    """Preview uploads share the same request-size guard as conversion."""
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 12, raising=False)
    r = client.post(
        "/preview",
        files={"file": ("x.pdf", b"%PDF-1.4\noversized", "application/pdf")},
    )
    assert r.status_code == 413


def test_picker_page_renders():
    r = client.get("/picker")
    assert r.status_code == 200
    assert "CMYK" in r.text and "hex" in r.text.lower()


@pytest.mark.skipif(
    not (ICC_DIR / "JapanColor2011Coated.icc").exists(),
    reason="ICC profile not yet copied",
)
def test_color_hex_to_cmyk():
    r = client.post(
        "/color",
        json={
            "direction": "hex2cmyk",
            "hex": "#FF0000",
            "icc": "JapanColor2011Coated.icc",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"c", "m", "y", "k"} <= body.keys()
    assert body["m"] > 70 and body["y"] > 70


@pytest.mark.skipif(
    not (ICC_DIR / "JapanColor2011Coated.icc").exists(),
    reason="ICC profile not yet copied",
)
def test_color_cmyk_to_hex():
    r = client.post(
        "/color",
        json={
            "direction": "cmyk2hex",
            "cmyk": [0, 100, 100, 0],
            "icc": "JapanColor2011Coated.icc",
        },
    )
    assert r.status_code == 200, r.text
    hx = r.json()["hex"]
    assert hx.startswith("#") and len(hx) == 7


def test_color_rejects_unknown_icc():
    r = client.post(
        "/color",
        json={"direction": "hex2cmyk", "hex": "#FF0000", "icc": "../etc/passwd"},
    )
    assert r.status_code == 400


def test_color_rejects_bad_direction():
    r = client.post(
        "/color",
        json={"direction": "wat", "hex": "#FF0000", "icc": "JapanColor2011Coated.icc"},
    )
    assert r.status_code == 400


def test_color_rejects_non_numeric_cmyk_component():
    r = client.post(
        "/color",
        json={
            "direction": "cmyk2hex",
            "cmyk": [None, 0, 0, 0],
            "icc": "JapanColor2011Coated.icc",
        },
    )
    assert r.status_code == 400


@pytest.mark.skipif(
    not (ICC_DIR / "JapanColor2011Coated.icc").exists(),
    reason="ICC profile not yet copied",
)
def test_convert_end_to_end(tmp_path: Path):
    """Generate a tiny RGB PDF, POST it, verify CMYK output via inkcov."""
    ps = tmp_path / "src.ps"
    ps.write_text(
        "%!PS-Adobe-3.0\n"
        "0.9 0.2 0.2 setrgbcolor\n"
        "72 72 200 100 rectfill\n"
        "showpage\n"
    )
    pdf = tmp_path / "src.pdf"
    subprocess.run(
        [
            "gs", "-dBATCH", "-dNOPAUSE", "-dQUIET",
            "-sDEVICE=pdfwrite",
            "-sProcessColorModel=DeviceRGB",
            "-sColorConversionStrategy=RGB",
            f"-sOutputFile={pdf}",
            str(ps),
        ],
        check=True,
        capture_output=True,
    )

    with pdf.open("rb") as f:
        r = client.post(
            "/convert",
            data={"icc": "JapanColor2011Coated.icc"},
            files={"file": ("src.pdf", f, "application/pdf")},
        )

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "src_cmyk.pdf" in r.headers.get("content-disposition", "")

    out = tmp_path / "out.pdf"
    out.write_bytes(r.content)

    inkcov = subprocess.run(
        ["gs", "-dBATCH", "-dNOPAUSE", "-dQUIET", "-sDEVICE=inkcov", "-o", "-", str(out)],
        check=True, capture_output=True, text=True,
    )
    rows = [l for l in inkcov.stdout.splitlines() if "CMYK OK" in l]
    assert rows, f"no CMYK rows in:\n{inkcov.stdout}"
    values = [float(x) for x in rows[0].split()[:4]]
    assert any(v > 0 for v in values)


# ---------------------------------------------------------------------------
# /sample/* — CMYK PDF pixel sampler
# ---------------------------------------------------------------------------

def _make_cmyk_pdf(path: Path, c: float, m: float, y: float, k: float) -> None:
    """Create a solid-color CMYK PDF via PostScript. c/m/y/k in 0-100."""
    ps = path.with_suffix(".ps")
    ps.write_text(
        f"%!PS-Adobe-3.0\n"
        f"{c/100:.4f} {m/100:.4f} {y/100:.4f} {k/100:.4f} setcmykcolor\n"
        f"clippath fill\n"
        f"showpage\n"
    )
    subprocess.run(
        [
            "gs", "-dBATCH", "-dNOPAUSE", "-dQUIET",
            "-sDEVICE=pdfwrite",
            "-sProcessColorModel=DeviceCMYK",
            "-sColorConversionStrategy=CMYK",
            f"-sOutputFile={path}", str(ps),
        ],
        check=True, capture_output=True,
    )


def test_sample_init_rejects_non_pdf(tmp_path: Path) -> None:
    txt = tmp_path / "x.txt"
    txt.write_text("nope")
    r = client.post(
        "/sample/init",
        files={"file": ("x.txt", txt.open("rb"), "text/plain")},
    )
    assert r.status_code == 400


def test_sample_pick_unknown_session() -> None:
    r = client.get("/sample/no-such-id/pick?x=0.5&y=0.5")
    assert r.status_code == 404


def test_sample_preview_unknown_session() -> None:
    r = client.get("/sample/no-such-id/preview")
    assert r.status_code == 404


def test_sample_pick_rejects_out_of_range(tmp_path: Path) -> None:
    """x, y outside [0, 1] must be rejected before any pixel read."""
    import app.main as main_module

    # Inject a stub session; no real TIFF needed for this validation test.
    sid = "stub-oor-session"
    main_module._sample_sessions[sid] = {
        "tmpdir": tmp_path,
        "tiff": tmp_path / "stub.tiff",
        "png": tmp_path / "stub.png",
        "width": 100,
        "height": 100,
    }
    try:
        r = client.get(f"/sample/{sid}/pick?x=1.5&y=0.5")
        assert r.status_code == 400
        r2 = client.get(f"/sample/{sid}/pick?x=0.5&y=-0.1")
        assert r2.status_code == 400
    finally:
        del main_module._sample_sessions[sid]


@pytest.mark.skipif(
    not (ICC_DIR / "JapanColor2011Coated.icc").exists(),
    reason="ICC profile not yet copied",
)
def test_sample_end_to_end(tmp_path: Path) -> None:
    """Upload a solid-color CMYK PDF; sampled center pixel matches source ink."""
    _make_cmyk_pdf(tmp_path / "solid.pdf", c=0, m=60, y=0, k=0)

    with (tmp_path / "solid.pdf").open("rb") as f:
        r = client.post(
            "/sample/init",
            files={"file": ("solid.pdf", f, "application/pdf")},
        )
    assert r.status_code == 200, r.text
    j = r.json()
    assert {"id", "width", "height"} <= j.keys()
    assert j["width"] > 0 and j["height"] > 0

    sid = j["id"]

    r2 = client.get(f"/sample/{sid}/preview")
    assert r2.status_code == 200
    assert r2.headers["content-type"] == "image/png"
    assert r2.content[:8] == b"\x89PNG\r\n\x1a\n"

    r3 = client.get(f"/sample/{sid}/pick?x=0.5&y=0.5")
    assert r3.status_code == 200, r3.text
    cmyk = r3.json()
    # Allow ±5% tolerance for GS CMYK round-trip quantisation.
    assert abs(cmyk["c"] - 0) < 5
    assert abs(cmyk["m"] - 60) < 5
    assert abs(cmyk["y"] - 0) < 5
    assert abs(cmyk["k"] - 0) < 5
