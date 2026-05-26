from __future__ import annotations

from pathlib import Path

import pytest

from app.services.text_extraction import OCRFallbackNotImplementedError, TextLayerChunkExtractor


def test_text_extractor_groups_by_chapter_and_filters_noise(monkeypatch) -> None:
    extractor = TextLayerChunkExtractor()

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [
                FakePage("ISBN 123456\n1\n2\n"),
                FakePage("第一章 总论\n这是第一段正文。这是第二句。\n"),
                FakePage("第二章 呼吸\n这是呼吸相关的正文段落，应当进入新的章节块。\n"),
            ]

    monkeypatch.setattr("app.services.text_extraction.PdfReader", FakeReader)

    chunks = extractor.extract_chunks(Path("fake.pdf"))

    assert len(chunks) == 2
    assert chunks[0].startswith("## 第一章 总论")
    assert "ISBN" not in chunks[0]
    assert chunks[1].startswith("## 第二章 呼吸")


def test_text_extractor_raises_ocr_placeholder_when_no_text(monkeypatch) -> None:
    extractor = TextLayerChunkExtractor()

    class FakePage:
        def extract_text(self) -> str:
            return ""

    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [FakePage()]

    monkeypatch.setattr("app.services.text_extraction.PdfReader", FakeReader)

    with pytest.raises(OCRFallbackNotImplementedError):
        extractor.extract_chunks(Path("fake.pdf"))
