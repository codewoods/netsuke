"""Spec for preview.py Ghostscript timeout behavior."""

import subprocess
from pathlib import Path

import pytest

from app.preview import pdf_to_cmyk_tiff, pdf_to_png


def test_pdf_to_png_uses_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preview rendering also needs a bounded Ghostscript process."""
    calls: list[dict] = []

    def fake_run(_cmd: list[str], **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(_cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf_to_png(tmp_path / "in.pdf", tmp_path / "out.png")
    assert calls and calls[0]["timeout"] > 0


def test_pdf_to_cmyk_tiff_uses_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CMYK rasterization must bound the Ghostscript subprocess."""
    calls: list[dict] = []

    def fake_run(_cmd: list[str], **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(_cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf_to_cmyk_tiff(tmp_path / "in.pdf", tmp_path / "out.tiff")
    assert calls and calls[0]["timeout"] > 0


def test_pdf_to_cmyk_tiff_uses_tiff32nc_device(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Must use tiff32nc so each pixel carries four 8-bit ink channels."""
    cmds: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs):
        cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf_to_cmyk_tiff(tmp_path / "in.pdf", tmp_path / "out.tiff")
    assert cmds and any("-sDEVICE=tiff32nc" in arg for arg in cmds[0])
