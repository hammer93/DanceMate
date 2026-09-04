"""Local OCR wrapper (v0.81.3).

`run_ocr` never calls the real tesseract binary in these tests - `runner` is
injected exactly like `acquisition.fetch`'s `opener` - so this suite is fast
and does not depend on tesseract being installed on the machine running it.
A handful of tests further down (`test_ocr_smoke.py`) do call the real
binary when it's available, and skip otherwise.
"""

from __future__ import annotations

import io

import pytest

from runtime import ocr

PIL = pytest.importorskip("PIL", reason="Pillow is required to build test images")
from PIL import Image  # noqa: E402


def _png_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_a_confident_result_is_ocr_success():
    result = ocr.run_ocr(_png_bytes(400, 300), runner=lambda img: ("THE PISTA MILONGA", 92.0))
    assert result.status == ocr.STATUS_SUCCESS
    assert result.text == "THE PISTA MILONGA"
    assert result.confidence == 92.0


def test_low_confidence_is_not_treated_as_a_usable_result():
    result = ocr.run_ocr(_png_bytes(400, 300), runner=lambda img: ("garbled text", 10.0))
    assert result.status == ocr.STATUS_LOW_CONFIDENCE
    assert not result.ok


def test_empty_text_is_low_confidence_even_with_a_high_score():
    """A blank/near-blank image can still score a meaningless high mean
    confidence over zero recognised words - text presence is checked too."""
    result = ocr.run_ocr(_png_bytes(400, 300), runner=lambda img: ("", 99.0))
    assert not result.ok


def test_a_tiny_image_is_rejected_before_ocr_runs():
    called = []
    result = ocr.run_ocr(_png_bytes(50, 50), runner=lambda img: called.append(1) or ("x", 99))
    assert result.status == ocr.STATUS_TOO_SMALL
    assert not called


def test_an_unreadable_image_fails_cleanly():
    result = ocr.run_ocr(b"not an image at all", runner=lambda img: ("x", 99))
    assert result.status == ocr.STATUS_FAILED


def test_a_runner_exception_fails_cleanly_not_raises():
    def boom(img):
        raise RuntimeError("tesseract binary not found")
    result = ocr.run_ocr(_png_bytes(400, 300), runner=boom)
    assert result.status == ocr.STATUS_FAILED
    assert "tesseract binary not found" in result.error


def test_a_custom_confidence_threshold_is_honoured():
    result = ocr.run_ocr(_png_bytes(400, 300), runner=lambda img: ("ok", 60.0),
                         min_confidence=70.0)
    assert result.status == ocr.STATUS_LOW_CONFIDENCE
