import base64
import io
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pypdf import PdfWriter

from dexter import llm
from dexter.config import settings
from dexter.rag import ingest, ocr


def scan_pdf(n=1):
    pdf = PdfWriter()
    for _ in range(n):
        pdf.add_blank_page(width=240, height=320)
    stream = io.BytesIO()
    pdf.write(stream)
    return stream.getvalue()


async def test_real_renderer_and_sdk_ocr_use_image_and_latin_text(
    respx_mock, monkeypatch, anthropic_client
):
    payload = scan_pdf()
    main_thread = threading.get_ident()
    render = ocr.render_page

    def checked(*args):
        assert threading.get_ident() != main_thread
        return render(*args)

    monkeypatch.setattr(ocr, "render_page", checked)
    request = respx_mock.post("https://api.anthropic.com/v1/messages").respond(
        200,
        json={
            "id": "msg_ocr",
            "type": "message",
            "role": "assistant",
            "model": settings().model_main,
            "content": [
                {"type": "text", "text": "Рок за пројекат Орион је двадесет први октобар."}
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
    )
    monkeypatch.setattr(llm, "client", lambda: anthropic_client)
    monkeypatch.setattr(llm.usage, "record", AsyncMock())
    result = await ingest.read_pdf(payload)
    assert result == "Rok za projekat Orion je dvadeset prvi oktobar."
    body = json.loads(request.calls[0].request.content)
    source = body["messages"][0]["content"][0]["source"]
    image = Image.open(io.BytesIO(base64.b64decode(source["data"])))
    assert image.size == (480, 640)
    assert source["media_type"] == "image/png"
    assert "PODATAK" in body["system"]
    assert llm.usage.record.await_args.args[1] == "ocr"


async def test_ocr_limit_native_pdf_and_incomplete_response(pdf_bytes, monkeypatch):
    original_read = ocr.read_page
    read = AsyncMock()
    monkeypatch.setattr(ocr, "read_page", read)
    assert "Dokument za proveru" in await ingest.read_pdf(pdf_bytes)
    read.assert_not_awaited()
    monkeypatch.setattr(settings(), "ocr_max_pages", 1)
    with pytest.raises(ValueError, match="OCR_MAX_PAGES=1"):
        await ingest.read_pdf(scan_pdf(2))
    read.assert_not_awaited()
    monkeypatch.setattr(ocr, "read_page", original_read)
    monkeypatch.setattr(
        llm,
        "create",
        AsyncMock(
            return_value=SimpleNamespace(
                stop_reason="max_tokens",
                content=[SimpleNamespace(type="text", text="Odsečen prepis")],
            )
        ),
    )
    store = AsyncMock()
    monkeypatch.setattr(ingest, "upsert_document", store)
    with pytest.raises(ValueError, match="nije potpun"):
        await ingest.ingest_file("sken.pdf", scan_pdf())
    store.assert_not_awaited()


async def test_mixed_pdf_preserves_native_pages_and_blank_ocr_is_allowed(pdf_bytes, monkeypatch):
    from pypdf import PdfReader

    pdf = PdfWriter()
    pdf.add_page(PdfReader(io.BytesIO(pdf_bytes)).pages[0])
    pdf.add_blank_page(width=240, height=320)
    out = io.BytesIO()
    pdf.write(out)
    read = AsyncMock(return_value="Prepis skenirane druge strane.")
    monkeypatch.setattr(ocr, "read_page", read)
    text = await ingest.read_pdf(out.getvalue())
    assert "Dokument za proveru" in text and text.endswith("druge strane.")
    assert read.await_args.args[1] == 1
    read.return_value = ""
    assert "Dokument za proveru" in await ingest.read_pdf(out.getvalue())
