"""Unit tests cho TextRenderer."""

from __future__ import annotations

import fitz
import pytest

from pdf_translator.font_manager import FontManager
from pdf_translator.models import TextBlock, TranslatedBlock
from pdf_translator.renderer import TextRenderer


def test_renderer_calculate_font_size() -> None:
    """Test thuật toán co giãn cỡ chữ (auto-shrink)."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    # Tạo một tài liệu nháp
    doc = fitz.open()
    page = doc.new_page()

    # Đăng ký font Regular để test
    font_name = fm.register_font(page, is_bold=False, is_italic=False)

    # 1. Text ngắn trong khung lớn -> giữ nguyên cỡ chữ gốc
    bbox_large = (100, 100, 400, 200)
    text_short = "Xin chào"
    size_1 = renderer._calculate_font_size(
        temp_page=page,
        text=text_short,
        bbox=bbox_large,
        original_size=12.0,
        min_size=6.0,
        font_name=font_name,
    )
    assert size_1 == 12.0

    # 2. Text rất dài trong khung siêu nhỏ -> phải co về min_size
    bbox_small = (100, 100, 150, 115)
    text_long = "Đây là một đoạn văn bản rất dài và chắc chắn sẽ bị tràn khung nếu dùng font chữ ban đầu."
    size_2 = renderer._calculate_font_size(
        temp_page=page,
        text=text_long,
        bbox=bbox_small,
        original_size=12.0,
        min_size=6.0,
        font_name=font_name,
    )
    assert size_2 == 6.0

    # 3. Kích thước trung bình -> co giãn về khoảng ở giữa (ví dụ: < 14 và > 6)
    bbox_medium = (100, 100, 200, 130)
    text_medium = "Đây là đoạn văn bản trung bình để test độ co giãn."
    size_3 = renderer._calculate_font_size(
        temp_page=page,
        text=text_medium,
        bbox=bbox_medium,
        original_size=14.0,
        min_size=6.0,
        font_name=font_name,
    )
    assert 6.0 <= size_3 <= 14.0

    doc.close()


def test_renderer_render_page() -> None:
    """Test quá trình render toàn diện một trang (redact và chèn text)."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    doc = fitz.open()
    page = doc.new_page()

    # Tạo các block giả lập
    original_block = TextBlock(
        block_id=0,
        text="Original English Text",
        bbox=(50, 50, 250, 80),
        font_size=12.0,
        font_name="Helvetica",
        color=(0, 0, 0),
        is_bold=False,
        is_italic=False,
        page_number=0,
    )

    translated_block = TranslatedBlock(
        original=original_block,
        translated_text="Văn bản tiếng Việt đã dịch",
        adjusted_font_size=12.0,
    )

    # Thực hiện render
    renderer.render_page(page, [translated_block], min_font_size=6.0)

    # Lấy văn bản trên trang để kiểm chứng
    page_text = page.get_text()
    
    # Text cũ phải được xóa, text mới phải hiển thị
    assert "Original English Text" not in page_text
    assert "Văn bản tiếng Việt" in page_text

    doc.close()
