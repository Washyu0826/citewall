"""On-prem Tesseract OCR backend (Q8 — "OCR 必跑", invariant #7).

Why this exists
---------------
The cloud Vision OCR path (`llm_client.vision_ocr`) is **forbidden** for
confidential / top_secret documents — their pages must never leave the box
(CLAUDE.md §4 invariant #7, Q15). Before this module there was simply no way
to OCR a *scanned* confidential PDF: the text layer is empty and cloud OCR is
off-limits, so extraction failed. This adds a real, local OCR path using
Tesseract so a confidential scan can be processed entirely on-prem.

Layering rules (CLAUDE.md §4)
-----------------------------
- AI Engine module — runs inside the AI Engine FastAPI process.
- Holds no business state. Writes to no DB.
- On-prem only: no network egress. Zero $ cost (the returned usage dict is
  all-zeros so the gateway's cost circuit breaker sees on-prem OCR as free).

Lazy import
-----------
`pytesseract` + the `tesseract` binary are an *optional* on-prem dependency
(see backend/requirements.txt). They are NOT installed in CI. We therefore
import lazily and raise a clear RuntimeError if either is missing, rather than
failing at module import and turning every test red.
"""

from __future__ import annotations

import io
import logging

from backend.shared.config import settings

logger = logging.getLogger(__name__)


def _zero_usage() -> dict:
    """On-prem OCR has no per-token cost — return an all-zero usage dict so the
    gateway's cost accounting / circuit breaker treats it as free."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "estimated_cost_usd": 0.0,
    }


def _require_tesseract():
    """Import pytesseract + verify the binary is reachable.

    Raises RuntimeError with an actionable message if either the Python
    binding or the underlying tesseract executable is unavailable. Callers
    should let this propagate — silently degrading to cloud OCR would violate
    invariant #7 for confidential docs.
    """
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:  # pragma: no cover — exercised via skip in CI
        raise RuntimeError(
            "OCR_BACKEND=tesseract but pytesseract is not installed. Install "
            "the optional on-prem OCR group: `pip install pytesseract` and the "
            "tesseract binary (e.g. `apt-get install tesseract-ocr "
            "tesseract-ocr-chi-tra`)."
        ) from exc

    try:
        # Cheap liveness probe: this shells out to `tesseract --version` and
        # raises pytesseract.TesseractNotFoundError if the binary is missing.
        pytesseract.get_tesseract_version()
    except Exception as exc:  # pragma: no cover — exercised via skip in CI
        raise RuntimeError(
            "OCR_BACKEND=tesseract but the `tesseract` binary was not found on "
            "PATH (pytesseract is installed but the engine is not). Install it "
            "with your OS package manager, e.g. `apt-get install tesseract-ocr "
            "tesseract-ocr-chi-tra`."
        ) from exc

    return pytesseract


def is_available() -> bool:
    """True iff pytesseract + the tesseract binary are usable. Never raises.

    Used by tests to skip the live-OCR assertion when the engine is absent
    (mirrors the Qdrant-reachable skip in test_vector_store_contract.py).
    """
    try:
        _require_tesseract()
        return True
    except Exception:
        return False


def ocr_image_sync(png_bytes: bytes, *, lang: str | None = None) -> tuple[str, dict]:
    """Blocking on-prem OCR of one rendered page (PNG bytes) → (text, usage).

    Traditional Chinese + English by default (`settings.OCR_TESSERACT_LANG`).
    This is synchronous/blocking (pytesseract shells out + waits); the async
    wrapper runs it in a threadpool so it never blocks the event loop.

    Raises RuntimeError if Tesseract is unavailable (see `_require_tesseract`).
    """
    if not png_bytes:
        # An empty render is not an error — just no text. Keeps the parser's
        # per-page loop robust to a blank scanned page.
        return "", _zero_usage()

    pytesseract = _require_tesseract()
    lang = lang or settings.OCR_TESSERACT_LANG

    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:  # pragma: no cover — Pillow ships with pytesseract
        raise RuntimeError(
            "OCR_BACKEND=tesseract requires Pillow (PIL) to decode the rendered "
            "page image. `pip install Pillow`."
        ) from exc

    with Image.open(io.BytesIO(png_bytes)) as img:
        text = pytesseract.image_to_string(img, lang=lang)

    return text.strip(), _zero_usage()


async def ocr_image(
    *, image_bytes: bytes, mime: str = "image/png", lang: str | None = None
) -> tuple[str, dict]:
    """Async wrapper matching `llm_client.vision_ocr`'s signature shape.

    Runs the blocking Tesseract call in a threadpool (`asyncio.to_thread`) so
    the parser's bounded-concurrency gather doesn't stall the event loop. The
    `mime` arg is accepted for signature parity with the cloud path; the page
    renderer always hands us PNG bytes.
    """
    import asyncio

    return await asyncio.to_thread(ocr_image_sync, image_bytes, lang=lang)


# ---------------------------------------------------------------------------
# PaddleOCR-VL (Q14 — production primary on-prem OCR)
# ---------------------------------------------------------------------------
#
# PaddleOCR-VL is a ~0.9B vision-language document parser (PaddleOCR 3.x) that
# handles Traditional Chinese layout, tables and formulas far better than
# Tesseract, and still runs entirely on-prem — so it is allowed for
# confidential scans. It fits an 8 GB GPU (RTX 3060) and also runs on CPU
# (slowly). `paddleocr` / `paddlepaddle(-gpu)` are OPTIONAL deps (root
# requirements.txt), lazily imported; when they are missing the parser falls
# back to Tesseract (see pdf_parser._ocr_page).

import threading  # noqa: E402

_paddle_pipeline = None
_paddle_lock = threading.Lock()


def _resolve_paddle_device(requested: str | None = None) -> str:
    """Map OCR_PADDLE_DEVICE (auto | cpu | gpu | gpu:N) to a Paddle device str."""
    requested = (requested or settings.OCR_PADDLE_DEVICE or "auto").strip().lower()
    if requested != "auto":
        return "gpu:0" if requested == "gpu" else requested
    try:
        import paddle  # type: ignore

        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu:0"
    except Exception:  # noqa: BLE001 — any probe failure means "no usable GPU"
        pass
    return "cpu"


def _require_paddle_vl():
    """Return the (cached) PaddleOCR-VL pipeline, building it on first use.

    Raises RuntimeError with install instructions when paddleocr (or its
    PaddleOCRVL pipeline) is unavailable, so the caller can fall back.
    """
    global _paddle_pipeline
    if _paddle_pipeline is not None:
        return _paddle_pipeline
    with _paddle_lock:
        if _paddle_pipeline is not None:
            return _paddle_pipeline
        try:
            from paddleocr import PaddleOCRVL  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "OCR_BACKEND=paddleocr-vl but paddleocr (>=3.3, with the "
                "PaddleOCRVL pipeline) is not installed. GPU: `pip install "
                "paddlepaddle-gpu` (matching your CUDA, see paddlepaddle.org.cn) "
                'then `pip install "paddleocr[doc-parser]"`; CPU: `pip install '
                'paddlepaddle "paddleocr[doc-parser]"`.'
            ) from exc
        device = _resolve_paddle_device()
        logger.info("loading PaddleOCR-VL pipeline on %s", device)
        try:
            _paddle_pipeline = PaddleOCRVL(device=device)
        except TypeError:  # older signature without device kwarg
            _paddle_pipeline = PaddleOCRVL()
        return _paddle_pipeline


def paddle_vl_available() -> bool:
    """True iff the paddleocr package with PaddleOCRVL can be imported. Never
    raises and never loads the model (cheap enough for health checks)."""
    try:
        from paddleocr import PaddleOCRVL  # type: ignore  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _paddle_result_to_text(res) -> str:
    """Extract plain text from one PaddleOCR-VL result object.

    The 3.x result exposes markdown (``res.markdown`` → dict with
    ``markdown_texts`` or a str) and a JSON view whose ``parsing_res_list``
    holds layout blocks with ``block_content``. Try those in order so minor
    API drift between releases doesn't break extraction.
    """
    md = getattr(res, "markdown", None)
    if isinstance(md, dict):
        text = md.get("markdown_texts") or md.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    elif isinstance(md, str) and md.strip():
        return md.strip()
    data = res if isinstance(res, dict) else getattr(res, "json", None)
    if callable(data):
        data = data()
    if isinstance(data, dict):
        data = data.get("res", data)
    blocks = data.get("parsing_res_list") or [] if isinstance(data, dict) else []
    parts = []
    for b in blocks:
        content = b.get("block_content") if isinstance(b, dict) else getattr(b, "content", None)
        if content:
            parts.append(str(content).strip())
    return "\n".join(p for p in parts if p)


def ocr_image_paddle_sync(png_bytes: bytes) -> tuple[str, dict]:
    """Blocking PaddleOCR-VL OCR of one rendered page (PNG bytes) → (text, usage).

    Raises RuntimeError when PaddleOCR-VL is unavailable (caller falls back).
    """
    if not png_bytes:
        return "", _zero_usage()
    pipeline = _require_paddle_vl()
    try:
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:  # pragma: no cover — both ship with paddleocr
        raise RuntimeError("OCR_BACKEND=paddleocr-vl requires numpy + Pillow") from exc

    with Image.open(io.BytesIO(png_bytes)) as img:
        arr = np.array(img.convert("RGB"))
    # predict() is not documented as thread-safe; serialise per process (the
    # 8 GB card can only hold one pipeline anyway).
    with _paddle_lock:
        results = list(pipeline.predict(arr))
    text = "\n\n".join(t for t in (_paddle_result_to_text(r) for r in results) if t)
    return text.strip(), _zero_usage()


async def ocr_image_paddle(
    *, image_bytes: bytes, mime: str = "image/png", lang: str | None = None
) -> tuple[str, dict]:
    """Async wrapper (threadpool) with the same signature as ``ocr_image``."""
    import asyncio

    return await asyncio.to_thread(ocr_image_paddle_sync, image_bytes)
