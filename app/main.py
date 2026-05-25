"""FastAPI app: upload RGB PDF or image, return CMYK PDF (+ preview PNG).

Endpoints:
    GET  /             rendered HTML form
    GET  /icc?paper=…  JSON list of ICC profiles for the chosen paper type
    POST /convert      multipart upload (file, icc) -> streams CMYK PDF
    POST /preview      multipart upload (file=PDF)  -> first-page PNG raster
    GET  /healthz      liveness probe for the CF Container runtime

All work happens inside a per-request tempdir, deleted on response close.
"""

import asyncio
import math
import os
import shutil
import subprocess
import tempfile
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Annotated, cast

from fastapi import Body, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from app import icc_catalog
from app.color import cmyk_to_hex, hex_to_cmyk
from app.convert import IMAGE_SUFFIXES, image_to_pdf, rgb_pdf_to_cmyk
from app.preview import pdf_to_cmyk_tiff, pdf_to_png

ACCEPTED_SUFFIXES: frozenset[str] = IMAGE_SUFFIXES | frozenset({".pdf"})

# Session registry for /sample/* endpoints.
# Maps session ID → {tmpdir, tiff, png, width, height}.
# Intended for local single-user use; oldest session evicted when cap is hit
# so the host filesystem doesn't accumulate unbounded tempfiles.
_MAX_SAMPLE_SESSIONS = 3
_sample_sessions: OrderedDict[str, dict] = OrderedDict()
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))

# ICC dir overridable by env so the same code runs locally (./icc) and
# inside the container (/app/icc baked at build time).
ICC_DIR = Path(os.environ.get("ICC_DIR", Path(__file__).parent.parent / "icc"))

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="netsuke CMYK converter")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the upload form with the default paper bucket pre-selected."""
    default_paper: icc_catalog.PaperType = "coated"
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "paper_labels": icc_catalog.PAPER_LABELS,
            "default_paper": default_paper,
            "profiles": icc_catalog.filter_by_paper(default_paper),
            "default_icc": icc_catalog.DEFAULTS[default_paper],
        },
    )


@app.get("/icc")
def list_icc(paper: str) -> JSONResponse:
    """Return ICC profiles matching the paper bucket, plus the default flag.

    Rejects unknown paper types up front so the client never gets an empty
    list and silently picks nothing.
    """
    if paper not in icc_catalog.PAPER_LABELS:
        raise HTTPException(400, f"unknown paper type: {paper}")
    typed = cast(icc_catalog.PaperType, paper)
    default = icc_catalog.DEFAULTS[typed]
    return JSONResponse(
        [
            {
                "filename": p.filename,
                "display": p.display,
                "region": p.region,
                "default": p.filename == default,
            }
            for p in icc_catalog.filter_by_paper(typed)
        ]
    )


@app.post("/convert")
async def convert(
    file: UploadFile,
    icc: Annotated[str, Form()],
) -> FileResponse:
    """Convert uploaded RGB PDF to CMYK PDF tagged with the chosen ICC.

    Validation: the icc field is matched against the static whitelist so
    a crafted filename like "../etc/passwd" can never escape ICC_DIR.
    The file extension check rejects obvious non-PDFs early; gs would
    catch the rest with a CalledProcessError.
    """
    if icc not in icc_catalog.allowed_filenames():
        raise HTTPException(400, f"icc profile not in catalog: {icc}")
    icc_path = ICC_DIR / icc
    if not icc_path.is_file():
        raise HTTPException(500, f"icc profile file missing on server: {icc}")

    if not file.filename:
        raise HTTPException(400, "upload missing filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ACCEPTED_SUFFIXES:
        raise HTTPException(
            400,
            f"unsupported file type: {suffix or '(none)'}; "
            f"accepted: .pdf, {', '.join(sorted(IMAGE_SUFFIXES))}",
        )

    # Create a tempdir we control the lifetime of (BackgroundTask cleans up).
    tmpdir = Path(tempfile.mkdtemp(prefix="netsuke_"))
    raw = tmpdir / f"src{suffix}"
    try:
        await _write_upload_limited(file, raw)
    except HTTPException:
        _cleanup(tmpdir)
        raise

    # Image inputs get wrapped into a single-page PDF first so the rest
    # of the pipeline stays unchanged. PDFs skip this step.
    src = tmpdir / "src.pdf"
    if suffix == ".pdf":
        src = raw
    else:
        try:
            await asyncio.to_thread(image_to_pdf, raw, src)
        except Exception as exc:
            _cleanup(tmpdir)
            raise HTTPException(400, f"image wrap failed: {exc}") from exc

    out_name = Path(file.filename).stem + "_cmyk.pdf"
    dst = tmpdir / out_name

    try:
        await asyncio.to_thread(rgb_pdf_to_cmyk, src, dst, icc_path)
    except subprocess.TimeoutExpired as exc:
        _cleanup(tmpdir)
        raise HTTPException(504, "conversion timed out") from exc
    except Exception as exc:
        _cleanup(tmpdir)
        raise HTTPException(500, "conversion failed") from exc

    return FileResponse(
        dst,
        media_type="application/pdf",
        filename=out_name,
        background=BackgroundTask(_cleanup, tmpdir),
    )


@app.get("/picker", response_class=HTMLResponse)
def picker(request: Request) -> HTMLResponse:
    """Render the bidirectional CMYK<->hex color picker page."""
    default_paper: icc_catalog.PaperType = "coated"
    return templates.TemplateResponse(
        request,
        "picker.html",
        {
            "paper_labels": icc_catalog.PAPER_LABELS,
            "default_paper": default_paper,
            "profiles": icc_catalog.filter_by_paper(default_paper),
            "default_icc": icc_catalog.DEFAULTS[default_paper],
        },
    )


@app.post("/color")
def color(payload: dict = Body(...)) -> JSONResponse:
    """Convert between sRGB hex and CMYK percentages via lcms.

    payload shape:
        { "direction": "hex2cmyk", "hex": "#RRGGBB", "icc": "<filename>" }
        { "direction": "cmyk2hex", "cmyk": [C,M,Y,K], "icc": "<filename>" }

    icc is matched against the static whitelist so a crafted filename
    cannot escape ICC_DIR (same defence as /convert).
    """
    icc = payload.get("icc", "")
    if icc not in icc_catalog.allowed_filenames():
        raise HTTPException(400, f"icc profile not in catalog: {icc}")
    icc_path = ICC_DIR / icc
    if not icc_path.is_file():
        raise HTTPException(500, f"icc profile file missing on server: {icc}")

    direction = payload.get("direction")
    try:
        if direction == "hex2cmyk":
            c, m, y, k = hex_to_cmyk(payload.get("hex", ""), icc_path)
            return JSONResponse({"c": c, "m": m, "y": y, "k": k})
        if direction == "cmyk2hex":
            cmyk = payload.get("cmyk")
            return JSONResponse({"hex": cmyk_to_hex(_parse_cmyk(cmyk), icc_path)})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    raise HTTPException(400, f"unknown direction: {direction!r}")


@app.post("/preview")
async def preview(file: UploadFile) -> FileResponse:
    """Rasterize the first page of an uploaded PDF to PNG.

    Used by the UI to feed color-blind simulator canvases on the
    client. The PNG is generated server-side because Ghostscript is
    already installed for the conversion pipeline; the browser only
    runs the cheap daltonize matrices.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "preview input must be a .pdf file")

    tmpdir = Path(tempfile.mkdtemp(prefix="netsuke_prev_"))
    src = tmpdir / "in.pdf"
    try:
        await _write_upload_limited(file, src)
    except HTTPException:
        _cleanup(tmpdir)
        raise
    png = tmpdir / "page1.png"
    try:
        await asyncio.to_thread(pdf_to_png, src, png)
    except subprocess.TimeoutExpired as exc:
        _cleanup(tmpdir)
        raise HTTPException(504, "preview render timed out") from exc
    except Exception as exc:
        _cleanup(tmpdir)
        raise HTTPException(500, "preview render failed") from exc
    return FileResponse(
        png,
        media_type="image/png",
        filename="preview.png",
        background=BackgroundTask(_cleanup, tmpdir),
    )


@app.post("/sample/init")
async def sample_init(file: UploadFile) -> JSONResponse:
    """Upload a PDF and rasterize it to a preview PNG + CMYK TIFF for ink sampling.

    Both rasters are produced at 72 dpi so display coordinates map 1:1 to
    TIFF pixel coordinates. The session ID returned here is used by
    /sample/{id}/preview and /sample/{id}/pick. Oldest session is evicted
    (tempdir deleted) when _MAX_SAMPLE_SESSIONS is exceeded, keeping the
    total live-file footprint bounded. Designed for local use where the PDF
    never leaves the machine.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "sample input must be a .pdf file")

    tmpdir = Path(tempfile.mkdtemp(prefix="netsuke_sample_"))
    src = tmpdir / "in.pdf"
    try:
        await _write_upload_limited(file, src)
    except HTTPException:
        _cleanup(tmpdir)
        raise

    png = tmpdir / "preview.png"
    tiff = tmpdir / "cmyk.tiff"
    try:
        await asyncio.gather(
            asyncio.to_thread(pdf_to_png, src, png, 72),
            asyncio.to_thread(pdf_to_cmyk_tiff, src, tiff, 72),
        )
    except subprocess.TimeoutExpired as exc:
        _cleanup(tmpdir)
        raise HTTPException(504, "rasterization timed out") from exc
    except Exception as exc:
        _cleanup(tmpdir)
        raise HTTPException(500, f"rasterization failed: {exc}") from exc

    from PIL import Image
    width, height = Image.open(png).size

    session_id = str(uuid.uuid4())
    while len(_sample_sessions) >= _MAX_SAMPLE_SESSIONS:
        _, old = _sample_sessions.popitem(last=False)
        _cleanup(old["tmpdir"])
    _sample_sessions[session_id] = {
        "tmpdir": tmpdir,
        "tiff": tiff,
        "png": png,
        "width": width,
        "height": height,
    }
    return JSONResponse({"id": session_id, "width": width, "height": height})


@app.get("/sample/{session_id}/preview")
def sample_preview(session_id: str) -> FileResponse:
    """Return the RGB preview PNG for the given sample session."""
    sess = _sample_sessions.get(session_id)
    if not sess:
        raise HTTPException(404, f"session not found: {session_id}")
    return FileResponse(sess["png"], media_type="image/png", filename="preview.png")


@app.get("/sample/{session_id}/pick")
def sample_pick(session_id: str, x: float, y: float) -> JSONResponse:
    """Return CMYK ink percentages (0-100) at normalised coordinates in [0, 1]².

    x=0 is left, y=0 is top. Reads the CMYK TIFF produced by sample_init;
    each channel is stored as 0-255 in the TIFF so we divide by 2.55 to get
    the 0-100% convention used everywhere else in this API.
    """
    sess = _sample_sessions.get(session_id)
    if not sess:
        raise HTTPException(404, f"session not found: {session_id}")
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise HTTPException(400, "x and y must be in [0, 1]")

    from PIL import Image
    img = Image.open(sess["tiff"])
    w, h = img.size
    px = min(int(x * w), w - 1)
    py = min(int(y * h), h - 1)
    c8, m8, y8, k8 = img.getpixel((px, py))
    return JSONResponse({
        "c": round(c8 / 2.55, 1),
        "m": round(m8 / 2.55, 1),
        "y": round(y8 / 2.55, 1),
        "k": round(k8 / 2.55, 1),
    })


def _cleanup(tmpdir: Path) -> None:
    """Best-effort recursive delete; runs after the response body is sent."""
    shutil.rmtree(tmpdir, ignore_errors=True)


async def _write_upload_limited(
    file: UploadFile,
    dst: Path,
    limit_bytes: int | None = None,
) -> None:
    """Write an upload in chunks while enforcing the current size limit.

    The multipart layer has already accepted the request by the time the
    endpoint runs, but chunked copying avoids adding a second full in-memory
    copy and stops bad inputs before they reach Ghostscript.
    """
    limit = MAX_UPLOAD_BYTES if limit_bytes is None else limit_bytes
    total = 0
    with dst.open("wb") as out:
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            total += len(chunk)
            if total > limit:
                raise HTTPException(413, f"upload exceeds {limit} bytes")
            out.write(chunk)


def _parse_cmyk(value: object) -> tuple[float, float, float, float]:
    """Validate JSON CMYK input before passing it to Little CMS.

    JSON can carry nulls, strings, infinities-as-strings, and nested values.
    Normalizing at the HTTP boundary keeps color.py focused on color science
    and ensures all malformed client input is reported as a 400.
    """
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("cmyk must be a 4-element list")
    try:
        parsed = tuple(float(v) for v in value)
    except (TypeError, ValueError) as exc:
        raise ValueError("cmyk values must be numeric") from exc
    if len(parsed) != 4 or not all(math.isfinite(v) for v in parsed):
        raise ValueError("cmyk values must be finite")
    return cast(tuple[float, float, float, float], parsed)
