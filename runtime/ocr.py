"""Local OCR of an already-fetched image (v0.81.3).

Tesseract 5, the `kor`+`eng` traineddata, run as a subprocess via
`pytesseract` - no network call, no paid Vision API, ~16MB installed
(measured on the ROCKPro64 board: `tesseract-ocr tesseract-ocr-kor
tesseract-ocr-eng`), ~1.2s and ~26MB peak RSS per poster-sized image on the
board's own RK3399. That is comfortably inside a 4GB board's budget for the
handful of images one source item ever has (see `image_fetch.MAX_IMAGES_PER_ITEM`).

Real event posters mix Korean, English and digits in one image, so both
language packs are loaded together (`kor+eng`) rather than picked per-image -
there is no cheap, reliable way to guess a poster's language before reading
it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

LANGUAGES = "kor+eng"

# Tesseract's own 0-100 confidence scale. A real poster with legible text
# scored ~90 in on-board measurement; this is a conservative first cut, not a
# tuned threshold - revisit once a larger sample of real event posters has
# gone through Section 55's before/after measurement.
MIN_CONFIDENCE = 50

MIN_WIDTH = 200
MIN_HEIGHT = 100

STATUS_SUCCESS = "OCR_SUCCESS"
STATUS_LOW_CONFIDENCE = "OCR_LOW_CONFIDENCE"
STATUS_FAILED = "OCR_FAILED"
STATUS_TOO_SMALL = "TOO_SMALL"


class OcrUnavailable(RuntimeError):
    """Tesseract, or its Python binding, is not installed."""


@dataclass
class OcrResult:
    status: str
    text: str = ""
    confidence: float | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SUCCESS


def _default_runner(image):
    """(text, mean_confidence) for a PIL Image, via pytesseract."""
    import pytesseract  # noqa: PLC0415 - only imported when OCR actually runs

    text = pytesseract.image_to_string(image, lang=LANGUAGES)
    data = pytesseract.image_to_data(image, lang=LANGUAGES, output_type=pytesseract.Output.DICT)
    confidences = [int(c) for c in data.get("conf", []) if str(c) not in ("-1", "")]
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return text, mean_confidence


def run_ocr(image_bytes: bytes, *, runner=None,
            min_confidence: float = MIN_CONFIDENCE) -> OcrResult:
    """OCR one already-fetched, already-type-validated image. Never raises."""
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError as exc:
        raise OcrUnavailable(f"Pillow not installed: {exc}") from exc

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        return OcrResult(status=STATUS_FAILED, error=f"cannot decode image: {exc}")

    width, height = image.size
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return OcrResult(
            status=STATUS_TOO_SMALL, width=width, height=height,
            error=f"{width}x{height} below the {MIN_WIDTH}x{MIN_HEIGHT} floor "
                  "(nav icons and profile avatars, not posters)",
        )

    do_ocr = runner or _default_runner
    try:
        text, confidence = do_ocr(image)
    except Exception as exc:
        return OcrResult(
            status=STATUS_FAILED, width=width, height=height,
            error=f"{type(exc).__name__}: {exc}",
        )

    text = (text or "").strip()
    if not text or confidence < min_confidence:
        return OcrResult(
            status=STATUS_LOW_CONFIDENCE, text=text, confidence=confidence,
            width=width, height=height,
        )
    return OcrResult(
        status=STATUS_SUCCESS, text=text, confidence=confidence,
        width=width, height=height,
    )
