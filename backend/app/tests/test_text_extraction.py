from __future__ import annotations

from pathlib import Path

import pytest

from app.services.text_extraction import OCRFallbackNotImplementedError, ParagraphChunk, TextLayerChunkExtractor


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
                FakePage("ISBN 123456\n1\n"),
                FakePage("1\n第一章 总论\n这是第一段正文。这是第二句。\n"),
                FakePage("第二章 呼吸\n这是呼吸相关的正文段落，应当进入新的章节。\n2"),
            ]

    monkeypatch.setattr("app.services.text_extraction.PdfReader", FakeReader)

    chunks = extractor.extract_chunks(Path("fake.pdf"))

    assert len(chunks) == 2
    assert isinstance(chunks[0], ParagraphChunk)
    assert chunks[0].section_path == "第一章 总论"
    assert chunks[0].page_number == 1
    assert "ISBN" not in chunks[0].text
    assert chunks[1].section_path == "第二章 呼吸"
    assert chunks[1].page_number == 2


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


def test_text_extractor_prefers_printed_page_number_from_page_edges(monkeypatch) -> None:
    extractor = TextLayerChunkExtractor()

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [
                FakePage("12\n第一章 总论\n这里是正文第一段，描述某个概念。\n"),
                FakePage("第二章 呼吸\n这里是正文第二段，介绍另一个概念。\n13"),
            ]

    monkeypatch.setattr("app.services.text_extraction.PdfReader", FakeReader)

    chunks = extractor.extract_chunks(Path("fake.pdf"))

    assert [chunk.page_number for chunk in chunks] == [12, 13]


def test_text_extractor_skips_standalone_subsection_titles(monkeypatch) -> None:
    extractor = TextLayerChunkExtractor()

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [
                FakePage(
                    "21\n"
                    "Chapter 1 Overview\n"
                    "Adrenocortical hormone effects\n"
                    "Adrenocortical hormones regulate metabolism and immune responses in multiple tissues.\n"
                )
            ]

    monkeypatch.setattr("app.services.text_extraction.PdfReader", FakeReader)

    chunks = extractor.extract_chunks(Path("fake.pdf"))

    assert len(chunks) == 1
    assert chunks[0].page_number == 21
    assert chunks[0].section_path == "Chapter 1 Overview / Adrenocortical hormone effects"
    assert chunks[0].text == "Adrenocortical hormones regulate metabolism and immune responses in multiple tissues."


def test_text_extractor_skips_pages_before_table_of_contents(monkeypatch) -> None:
    extractor = TextLayerChunkExtractor()

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [
                FakePage("Preface\nThis preface page should not be parsed into chunks.\n"),
                FakePage(
                    "Contents\n"
                    "Chapter 1 Overview ........ 1\n"
                    "Chapter 2 Respiration ........ 23\n"
                    "Chapter 3 Circulation ........ 45\n"
                ),
                FakePage("1\nChapter 1 Overview\nThis is the first body paragraph after the table of contents.\n"),
            ]

    monkeypatch.setattr("app.services.text_extraction.PdfReader", FakeReader)

    chunks = extractor.extract_chunks(Path("fake.pdf"))

    assert len(chunks) == 1
    assert chunks[0].page_number == 1
    assert chunks[0].section_path == "Chapter 1 Overview"
    assert chunks[0].text == "This is the first body paragraph after the table of contents."
