"""PaddleOCR-VL backend (Q14): routing, confidential enforcement, Tesseract
fallback and result parsing — all with fakes, no paddle install needed."""

from __future__ import annotations

import asyncio
import io
import sys
import types

import pytest

from backend.ai_engine import ocr_local, pdf_parser
from backend.shared.config import settings


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_pipeline(monkeypatch):
    monkeypatch.setattr(ocr_local, "_paddle_pipeline", None)


@pytest.mark.parametrize("level", ["confidential", "top_secret"])
def test_confidential_allows_paddle_vl(monkeypatch, level):
    monkeypatch.setattr(settings, "OCR_BACKEND", "paddleocr-vl")
    assert pdf_parser._resolve_ocr_backend(level) == "paddleocr-vl"


def test_confidential_still_refuses_cloud(monkeypatch):
    monkeypatch.setattr(settings, "OCR_BACKEND", "vision")
    with pytest.raises(RuntimeError) as ei:
        pdf_parser._resolve_ocr_backend("confidential")
    assert "paddleocr-vl" in str(ei.value) and "tesseract" in str(ei.value)


def test_paddle_page_routes_local(monkeypatch):
    calls = {"paddle": 0, "tess": 0, "cloud": 0}

    async def _paddle(*, image_bytes, mime="image/png", lang=None):
        calls["paddle"] += 1
        return "PADDLE", pdf_parser._zero_usage()

    async def _tess(*, image_bytes, mime="image/png", lang=None):
        calls["tess"] += 1
        return "TESS", pdf_parser._zero_usage()

    async def _cloud(**_kw):
        calls["cloud"] += 1
        return "CLOUD", pdf_parser._zero_usage()

    monkeypatch.setattr(settings, "OCR_BACKEND", "paddleocr-vl")
    monkeypatch.setattr(ocr_local, "ocr_image_paddle", _paddle)
    monkeypatch.setattr(ocr_local, "ocr_image", _tess)
    monkeypatch.setattr(pdf_parser.llm_client, "vision_ocr", _cloud)

    text, _ = _run(pdf_parser._ocr_page(b"png", security_level="confidential"))
    assert text == "PADDLE"
    assert calls == {"paddle": 1, "tess": 0, "cloud": 0}


def test_paddle_unavailable_falls_back_to_tesseract_never_cloud(monkeypatch):
    calls = {"tess": 0, "cloud": 0}

    async def _paddle(*, image_bytes, mime="image/png", lang=None):
        raise RuntimeError("paddleocr not installed")

    async def _tess(*, image_bytes, mime="image/png", lang=None):
        calls["tess"] += 1
        return "TESS", pdf_parser._zero_usage()

    async def _cloud(**_kw):
        calls["cloud"] += 1
        return "CLOUD", pdf_parser._zero_usage()

    monkeypatch.setattr(settings, "OCR_BACKEND", "paddleocr-vl")
    monkeypatch.setattr(ocr_local, "ocr_image_paddle", _paddle)
    monkeypatch.setattr(ocr_local, "ocr_image", _tess)
    monkeypatch.setattr(pdf_parser.llm_client, "vision_ocr", _cloud)

    text, _ = _run(pdf_parser._ocr_page(b"png", security_level="confidential"))
    assert text == "TESS"
    assert calls == {"tess": 1, "cloud": 0}


def test_require_paddle_missing_raises_with_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "paddleocr", None)  # import -> ImportError
    with pytest.raises(RuntimeError) as ei:
        ocr_local._require_paddle_vl()
    assert "paddlepaddle-gpu" in str(ei.value)
    assert ocr_local.paddle_vl_available() is False


def _png() -> bytes:
    Image = pytest.importorskip("PIL.Image")  # Pillow/numpy ship with paddleocr
    pytest.importorskip("numpy")

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_paddle_sync_with_fake_pipeline(monkeypatch):
    seen = {}

    class _Res:
        markdown = {"markdown_texts": "審查意見通知函\n請求項1"}

    class _FakeVL:
        def __init__(self, device=None):
            seen["device"] = device

        def predict(self, arr):
            seen["shape"] = getattr(arr, "shape", None)
            return [_Res()]

    monkeypatch.setitem(sys.modules, "paddleocr", types.SimpleNamespace(PaddleOCRVL=_FakeVL))
    monkeypatch.setattr(settings, "OCR_PADDLE_DEVICE", "cpu")
    text, usage = ocr_local.ocr_image_paddle_sync(_png())
    assert text == "審查意見通知函\n請求項1"
    assert usage["estimated_cost_usd"] == 0.0
    assert seen["device"] == "cpu"
    assert seen["shape"][:2] == (8, 8)


def test_paddle_empty_page_is_not_an_error():
    assert ocr_local.ocr_image_paddle_sync(b"") == ("", ocr_local._zero_usage())


def test_result_to_text_fallbacks():
    # markdown as plain string
    assert ocr_local._paddle_result_to_text(types.SimpleNamespace(markdown=" 甲 ")) == "甲"
    # json view with parsing_res_list blocks
    res = {"res": {"parsing_res_list": [{"block_content": "第一段"}, {"block_content": "第二段"}]}}
    assert ocr_local._paddle_result_to_text(res) == "第一段\n第二段"
    # json() callable
    obj = types.SimpleNamespace(
        markdown=None, json=lambda: {"parsing_res_list": [{"block_content": "X"}]}
    )
    assert ocr_local._paddle_result_to_text(obj) == "X"
    assert ocr_local._paddle_result_to_text(object()) == ""


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("cpu", "cpu"), ("gpu", "gpu:0"), ("gpu:1", "gpu:1")],
)
def test_explicit_device(requested, expected):
    assert ocr_local._resolve_paddle_device(requested) == expected


def test_auto_device_without_paddle_is_cpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "paddle", None)
    assert ocr_local._resolve_paddle_device("auto") == "cpu"


def test_figure_regions_confidential_ok_on_paddle(monkeypatch):
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "x")
    pdf = doc.tobytes()
    monkeypatch.setattr(settings, "OCR_BACKEND", "paddleocr-vl")
    assert _run(pdf_parser.extract_figure_regions(pdf, 0, security_level="confidential")) == []
