"""Unit tests cho Translator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pdf_translator.models import AppConfig, TextBlock
from pdf_translator.translator import Translator


@pytest.mark.asyncio
async def test_translator_success() -> None:
    """Test dịch thành công khi API trả về đúng định dạng ngay lần đầu."""
    config = AppConfig(api_key="test-key")
    translator = Translator(config)

    # Mock API response
    mock_create = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content="[1] Xin chào thế giới\n[2] Tài liệu mẫu"
            )
        )
    ]
    mock_create.return_value = mock_response
    translator.client.chat.completions.create = mock_create

    blocks = [
        TextBlock(
            block_id=0,
            text="Hello world",
            bbox=(0, 0, 100, 20),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
        TextBlock(
            block_id=1,
            text="Sample document",
            bbox=(0, 30, 100, 50),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
    ]

    translated = await translator.translate_page(blocks)

    assert len(translated) == 2
    assert translated[0].translated_text == "Xin chào thế giới"
    assert translated[0].original == blocks[0]
    assert translated[1].translated_text == "Tài liệu mẫu"
    assert translated[1].original == blocks[1]

    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_translator_retry_success() -> None:
    """Test cơ chế retry thành công khi lần đầu trả về định dạng sai."""
    config = AppConfig(api_key="test-key")
    translator = Translator(config)

    mock_create = AsyncMock()
    # Lần 1: Trả về thiếu block [2]
    mock_response_bad = MagicMock()
    mock_response_bad.choices = [
        MagicMock(message=MagicMock(content="[1] Xin chào thế giới"))
    ]
    # Lần 2: Trả về đầy đủ
    mock_response_good = MagicMock()
    mock_response_good.choices = [
        MagicMock(
            message=MagicMock(
                content="[1] Xin chào thế giới\n[2] Tài liệu mẫu"
            )
        )
    ]

    mock_create.side_effect = [mock_response_bad, mock_response_good]
    translator.client.chat.completions.create = mock_create

    blocks = [
        TextBlock(
            block_id=0,
            text="Hello world",
            bbox=(0, 0, 100, 20),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
        TextBlock(
            block_id=1,
            text="Sample document",
            bbox=(0, 30, 100, 50),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
    ]

    translated = await translator.translate_page(blocks)

    assert len(translated) == 2
    assert translated[0].translated_text == "Xin chào thế giới"
    assert translated[1].translated_text == "Tài liệu mẫu"

    assert mock_create.call_count == 2


@pytest.mark.asyncio
async def test_translator_fallback_on_missing_blocks() -> None:
    """Test cơ chế fallback khi cả 2 lần đều trả về thiếu block (giữ nguyên gốc block thiếu)."""
    config = AppConfig(api_key="test-key")
    translator = Translator(config)

    mock_create = AsyncMock()
    # Cả hai lần đều trả về thiếu block [2]
    mock_response_bad = MagicMock()
    mock_response_bad.choices = [
        MagicMock(message=MagicMock(content="[1] Xin chào thế giới"))
    ]

    mock_create.side_effect = [mock_response_bad, mock_response_bad]
    translator.client.chat.completions.create = mock_create

    blocks = [
        TextBlock(
            block_id=0,
            text="Hello world",
            bbox=(0, 0, 100, 20),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
        TextBlock(
            block_id=1,
            text="Sample document",
            bbox=(0, 30, 100, 50),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
    ]

    translated = await translator.translate_page(blocks)

    assert len(translated) == 2
    assert translated[0].translated_text == "Xin chào thế giới"  # Dịch được
    assert (
        translated[1].translated_text == "Sample document"
    )  # Fallback về text gốc

    assert mock_create.call_count == 2


@pytest.mark.asyncio
async def test_translator_api_exception_retry_and_fallback() -> None:
    """Test gọi API ném ngoại lệ ở lần đầu, và thành công ở lần sau, hoặc lỗi toàn bộ."""
    config = AppConfig(api_key="test-key")
    translator = Translator(config)

    # Thử nghiệm 1: Lần 1 ném exception, lần 2 thành công
    mock_create = AsyncMock()
    mock_response_good = MagicMock()
    mock_response_good.choices = [
        MagicMock(
            message=MagicMock(
                content="[1] Xin chào thế giới\n[2] Tài liệu mẫu"
            )
        )
    ]
    mock_create.side_effect = [
        Exception("API connection timeout"),
        mock_response_good,
    ]
    translator.client.chat.completions.create = mock_create

    blocks = [
        TextBlock(
            block_id=0,
            text="Hello world",
            bbox=(0, 0, 100, 20),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
        TextBlock(
            block_id=1,
            text="Sample document",
            bbox=(0, 30, 100, 50),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
    ]

    translated = await translator.translate_page(blocks)
    assert len(translated) == 2
    assert translated[0].translated_text == "Xin chào thế giới"
    assert translated[1].translated_text == "Tài liệu mẫu"
    assert mock_create.call_count == 2


def test_translator_build_prompt_with_table_cells() -> None:
    """Test xây dựng prompt chứa marker (Table Cell) cho ô bảng."""
    config = AppConfig(api_key="test-key")
    translator = Translator(config)

    blocks = [
        TextBlock(
            block_id=0,
            text="Hello world",
            bbox=(0, 0, 100, 20),
            font_size=10.0,
            font_name="helv",
            color=0,
            is_table_cell=False,
        ),
        TextBlock(
            block_id=1,
            text="Table Content",
            bbox=(0, 30, 100, 50),
            font_size=10.0,
            font_name="helv",
            color=0,
            is_table_cell=True,
        ),
    ]

    prompt = translator._build_prompt(blocks)
    assert "[1] Hello world" in prompt
    assert "[2] (Table Cell) Table Content" in prompt


def test_translator_parse_response_removes_table_cell_marker() -> None:
    """Test parse response loại bỏ marker (Table Cell) nếu LLM vô tình lặp lại."""
    config = AppConfig(api_key="test-key")
    translator = Translator(config)

    blocks = [
        TextBlock(
            block_id=0,
            text="Table Content",
            bbox=(0, 0, 100, 20),
            font_size=10.0,
            font_name="helv",
            color=0,
            is_table_cell=True,
        )
    ]

    response = "[1] (Table Cell) Nội dung bảng"
    parsed_map = translator._parse_response(response, blocks)
    assert parsed_map[0] == "Nội dung bảng"

    response_no_marker = "[1] Nội dung bảng"
    parsed_map_no_marker = translator._parse_response(response_no_marker, blocks)
    assert parsed_map_no_marker[0] == "Nội dung bảng"

