"""Unit tests cho models.py."""

from __future__ import annotations

import pytest

from pdf_translator.models import (
    AppConfig,
    TextBlock,
    TranslatedBlock,
    TranslationResult,
)


class TestTextBlock:
    def test_basic_creation(self):
        block = TextBlock(
            block_id=0,
            text="Hello world",
            bbox=(10.0, 20.0, 110.0, 40.0),
            font_size=12.0,
            font_name="Helvetica",
            color=(0.0, 0.0, 0.0),
        )
        assert block.block_id == 0
        assert block.text == "Hello world"
        assert block.is_bold is False
        assert block.is_italic is False
        assert block.page_number == 0
        assert block.is_table_cell is False

    def test_table_cell_creation(self):
        block = TextBlock(
            block_id=0,
            text="Cell",
            bbox=(10, 20, 110, 40),
            font_size=10.0,
            font_name="Helvetica",
            color=(0.0, 0.0, 0.0),
            is_table_cell=True,
        )
        assert block.is_table_cell is True

    def test_width_height(self):
        block = TextBlock(
            block_id=1,
            text="Test",
            bbox=(10.0, 20.0, 110.0, 50.0),
            font_size=12.0,
            font_name="Helvetica",
            color=(0.0, 0.0, 0.0),
        )
        assert block.width == 100.0
        assert block.height == 30.0

    def test_color_rgb_tuple(self):
        block = TextBlock(
            block_id=0,
            text="x",
            bbox=(0, 0, 10, 10),
            font_size=10,
            font_name="F",
            color=(0.5, 0.25, 0.75),
        )
        assert block.color_rgb == (0.5, 0.25, 0.75)

    def test_color_rgb_from_int(self):
        # 0xFF8000 = R=255, G=128, B=0
        block = TextBlock(
            block_id=0,
            text="x",
            bbox=(0, 0, 10, 10),
            font_size=10,
            font_name="F",
            color=0xFF8000,
        )
        r, g, b = block.color_rgb
        assert abs(r - 1.0) < 0.01
        assert abs(g - 128 / 255) < 0.01
        assert abs(b - 0.0) < 0.01

    def test_bold_italic_flags(self):
        block = TextBlock(
            block_id=0,
            text="Bold",
            bbox=(0, 0, 10, 10),
            font_size=12,
            font_name="F",
            color=(0, 0, 0),
            is_bold=True,
            is_italic=True,
        )
        assert block.is_bold is True
        assert block.is_italic is True


class TestTranslatedBlock:
    def _make_block(self) -> TextBlock:
        return TextBlock(
            block_id=0,
            text="Hello",
            bbox=(0, 0, 100, 20),
            font_size=12,
            font_name="F",
            color=(0, 0, 0),
        )

    def test_creation(self):
        orig = self._make_block()
        tb = TranslatedBlock(
            original=orig,
            translated_text="Xin chào",
            adjusted_font_size=12.0,
        )
        assert tb.translated_text == "Xin chào"
        assert tb.adjusted_font_size == 12.0

    def test_negative_font_size_raises(self):
        orig = self._make_block()
        with pytest.raises(ValueError, match="adjusted_font_size"):
            TranslatedBlock(original=orig, translated_text="x", adjusted_font_size=0.0)


class TestTranslationResult:
    def test_default_success(self):
        result = TranslationResult(page_number=0)
        assert result.success is True
        assert result.error is None
        assert result.blocks == []

    def test_error_result(self):
        result = TranslationResult(
            page_number=1, success=False, error="API timeout"
        )
        assert result.success is False
        assert result.error == "API timeout"


class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.api_key == ""
        assert cfg.api_base_url == "https://api.deepseek.com"
        assert cfg.model == "deepseek-chat"
        assert cfg.concurrency == 5
        assert cfg.min_font_size == 6.0
        assert cfg.log_level == "INFO"
        assert cfg.log_file is None
