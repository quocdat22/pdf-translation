"""Unit tests cho Translator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pdf_translator.models import AppConfig, TextBlock
from pdf_translator.translator import Translator


@pytest.mark.asyncio
async def test_translator_success() -> None:
    """Test dịch thành công khi API trả về đúng định dạng ngay lần đầu."""
    config = AppConfig(api_key="test-key", use_cache=False)
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
    config = AppConfig(api_key="test-key", use_cache=False)
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
    config = AppConfig(api_key="test-key", use_cache=False)
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
    config = AppConfig(api_key="test-key", use_cache=False)
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


@pytest.mark.asyncio
async def test_translator_regex_bracket_inside_text() -> None:
    """Test khả năng parse regex của translator khi văn bản dịch có chứa dấu ngoặc vuông số ở giữa câu."""
    config = AppConfig(api_key="test-key")
    translator = Translator(config)

    blocks = [
        TextBlock(
            block_id=0,
            text="First item",
            bbox=(0, 0, 100, 20),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
        TextBlock(
            block_id=1,
            text="Second item",
            bbox=(0, 30, 100, 50),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
    ]

    response = "\n[1] Mục thứ nhất: [1] giá trị một\n[2] Mục thứ hai: [2] giá trị hai"
    parsed_map = translator._parse_response(response, blocks)
    assert parsed_map[0] == "Mục thứ nhất: [1] giá trị một"
    assert parsed_map[1] == "Mục thứ hai: [2] giá trị hai"


@pytest.mark.asyncio
async def test_translator_complete_failure_propagates_exception() -> None:
    """Test cơ chế propagate lỗi lên processor khi cả 2 lần gọi API dịch đều quăng ngoại lệ."""
    config = AppConfig(api_key="test-key", use_cache=False)
    translator = Translator(config)

    mock_call_api = AsyncMock()
    mock_call_api.side_effect = [
        Exception("API Call 1 failed"),
        Exception("API Call 2 failed"),
    ]
    translator._call_api = mock_call_api

    blocks = [
        TextBlock(
            block_id=0,
            text="Hello world",
            bbox=(0, 0, 100, 20),
            font_size=10.0,
            font_name="helv",
            color=0,
        ),
    ]

    with pytest.raises(Exception, match="API Call 2 failed"):
        await translator.translate_page(blocks)

    assert mock_call_api.call_count == 2


@pytest.mark.asyncio
async def test_translator_with_cache() -> None:
    """Test translator đọc bản dịch từ cache và ghi các bản dịch mới vào cache."""
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        config = AppConfig(api_key="test-key", use_cache=True)
        translator = Translator(config)
        from pdf_translator.cache import TranslationCache
        translator.cache = TranslationCache(db_path)

        # 1. Chuẩn bị 2 block. Block 1 đã có trong cache, Block 2 thì chưa.
        translator.cache.set("Cached text", "Bản dịch đã lưu", "English", "Vietnamese", "deepseek-chat")

        blocks = [
            TextBlock(
                block_id=0,
                text="Cached text",
                bbox=(0, 0, 100, 20),
                font_size=10.0,
                font_name="helv",
                color=0,
            ),
            TextBlock(
                block_id=1,
                text="Uncached text",
                bbox=(0, 30, 100, 50),
                font_size=10.0,
                font_name="helv",
                color=0,
            ),
        ]

        # Mock API chỉ nhận được 1 block cần dịch (Uncached text)
        mock_call_api = AsyncMock()
        mock_call_api.return_value = "[1] Bản dịch mới"
        translator._call_api = mock_call_api

        # Thực hiện dịch trang
        translated = await translator.translate_page(blocks)

        assert len(translated) == 2
        # Block 1 được nạp từ cache
        assert translated[0].translated_text == "Bản dịch đã lưu"
        # Block 2 được dịch qua API
        assert translated[1].translated_text == "Bản dịch mới"

        # Kiểm tra xem API chỉ được gọi đúng 1 lần với prompt cho 1 block
        mock_call_api.assert_called_once()
        called_prompt = mock_call_api.call_args[0][1]
        assert "[1] Uncached text" in called_prompt
        assert "Cached text" not in called_prompt

        # Kiểm tra xem block 2 đã được lưu vào cache chưa
        cached_val = translator.cache.get("Uncached text", "English", "Vietnamese", "deepseek-chat")
        assert cached_val == "Bản dịch mới"

    finally:
        try:
            if db_path.exists():
                db_path.unlink()
        except PermissionError:
            pass


def test_translator_build_prompt_with_semantic_info() -> None:
    """Test xây dựng prompt chứa ngữ cảnh ngữ nghĩa (role, context)."""
    config = AppConfig(api_key="test-key")
    translator = Translator(config)

    blocks = [
        TextBlock(
            block_id=0,
            text="Heading Text",
            bbox=(0, 0, 100, 20),
            font_size=12.0,
            font_name="helv",
            color=0,
            semantic_role="heading",
            semantic_context="Chapter Title",
        ),
        TextBlock(
            block_id=1,
            text="Caption Text",
            bbox=(0, 30, 100, 50),
            font_size=10.0,
            font_name="helv",
            color=0,
            semantic_role="figure_caption",
            semantic_context="Graph description",
        ),
    ]

    prompt = translator._build_prompt(blocks)
    assert "[1] (Role: Heading) (Context: Chapter Title) Heading Text" in prompt
    assert "[2] (Role: Figure Caption) (Context: Graph description) Caption Text" in prompt


def test_translator_parse_response_removes_semantic_markers() -> None:
    """Test parse response loại bỏ marker (Role) và (Context) lặp lại."""
    config = AppConfig(api_key="test-key")
    translator = Translator(config)

    blocks = [
        TextBlock(
            block_id=0,
            text="Heading Text",
            bbox=(0, 0, 100, 20),
            font_size=12.0,
            font_name="helv",
            color=0,
            semantic_role="heading",
            semantic_context="Chapter Title",
        )
    ]

    response = "[1] (Role: Heading) (Context: Chapter Title) Tiêu đề chương"
    parsed_map = translator._parse_response(response, blocks)
    assert parsed_map[0] == "Tiêu đề chương"

    response_mixed = "[1] (Role: Heading) (Context: Chapter Title) (Table Cell) Tiêu đề"
    parsed_map_mixed = translator._parse_response(response_mixed, blocks)
    assert parsed_map_mixed[0] == "Tiêu đề"




