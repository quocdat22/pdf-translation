"""Unit tests cho PDFProcessor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest
import fitz

from pdf_translator.models import AppConfig
from pdf_translator.processor import PDFProcessor


@pytest.mark.asyncio
async def test_processor_dry_run(tmp_path) -> None:
    """Test dry-run mode của PDFProcessor (không gọi dịch và không lưu file mới)."""
    # Tạo PDF thật ngắn
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(50, 50, 200, 100),
        "Hello from page 1",
        fontsize=12,
    )
    pdf_path = tmp_path / "input.pdf"
    doc.save(pdf_path)
    doc.close()

    config = AppConfig(api_key="test-key")
    processor = PDFProcessor(config)

    # Mock translator call
    processor.translator.translate_page = AsyncMock()

    output_path = tmp_path / "output.pdf"
    
    # Chạy dry-run
    await processor.process(
        input_path=str(pdf_path),
        output_path=str(output_path),
        dry_run=True,
    )

    # Đảm bảo không gọi dịch
    processor.translator.translate_page.assert_not_called()
    # Đảm bảo không tạo file output mới
    assert not output_path.exists()


@pytest.mark.asyncio
async def test_processor_end_to_end(tmp_path) -> None:
    """Test pipeline dịch toàn bộ với mock Translator."""
    # Tạo PDF thật
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(50, 50, 250, 100),
        "Translate this sentence.",
        fontsize=12,
    )
    pdf_path = tmp_path / "input.pdf"
    doc.save(pdf_path)
    doc.close()

    config = AppConfig(api_key="test-key")
    processor = PDFProcessor(config)

    # Mock translate_page
    from pdf_translator.models import TranslatedBlock
    
    async def mock_translate(blocks):
        return [
            TranslatedBlock(
                original=block,
                translated_text="Dịch câu này.",
                adjusted_font_size=block.font_size
            )
            for block in blocks
        ]
        
    processor.translator.translate_page = mock_translate

    output_path = tmp_path / "output.pdf"

    await processor.process(
        input_path=str(pdf_path),
        output_path=str(output_path),
        dry_run=False,
    )

    assert output_path.exists()

    # Kiểm tra nội dung file output
    out_doc = fitz.open(output_path)
    out_text = out_doc[0].get_text()
    
    assert "Translate this sentence." not in out_text
    assert "Dịch câu này." in out_text
    out_doc.close()


@pytest.mark.asyncio
async def test_processor_page_failure(tmp_path) -> None:
    """Test xử lý lỗi khi một trang dịch thất bại."""
    # Tạo PDF 2 trang
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_textbox(fitz.Rect(50, 50, 200, 100), "Hello page 1", fontsize=12)
    page2 = doc.new_page()
    page2.insert_textbox(fitz.Rect(50, 50, 200, 100), "Hello page 2", fontsize=12)
    
    pdf_path = tmp_path / "input.pdf"
    doc.save(pdf_path)
    doc.close()

    config = AppConfig(api_key="test-key")
    processor = PDFProcessor(config)

    # Mock translate_page ném exception
    processor.translator.translate_page = AsyncMock(side_effect=Exception("Translation Error"))

    output_path = tmp_path / "output.pdf"

    # Run pipeline - không bị crash và vẫn lưu file output (giữ text gốc)
    await processor.process(
        input_path=str(pdf_path),
        output_path=str(output_path),
        dry_run=False,
    )

    assert output_path.exists()
    out_doc = fitz.open(output_path)
    # Vì lỗi dịch nên text gốc vẫn giữ nguyên
    assert "Hello page 1" in out_doc[0].get_text()
    assert "Hello page 2" in out_doc[1].get_text()
    out_doc.close()


@pytest.mark.asyncio
async def test_processor_bilingual_mode(tmp_path) -> None:
    """Test PDFProcessor với chế độ bilingual song ngữ song song."""
    # Tạo PDF 2 trang
    doc = fitz.open()
    page1 = doc.new_page(width=300, height=400)
    page1.insert_textbox(fitz.Rect(50, 50, 250, 100), "Hello page 1", fontsize=12)
    page2 = doc.new_page(width=300, height=400)
    page2.insert_textbox(fitz.Rect(50, 50, 250, 100), "Hello page 2", fontsize=12)
    
    pdf_path = tmp_path / "input.pdf"
    doc.save(pdf_path)
    doc.close()

    # Cấu hình bilingual = True
    config = AppConfig(api_key="test-key", bilingual=True)
    processor = PDFProcessor(config)

    # Mock translate_page
    from pdf_translator.models import TranslatedBlock
    
    async def mock_translate(blocks):
        return [
            TranslatedBlock(
                original=block,
                translated_text="Xin chào trang 1",
                adjusted_font_size=block.font_size
            )
            for block in blocks
        ]
        
    processor.translator.translate_page = mock_translate

    output_path = tmp_path / "output.pdf"

    # Chỉ dịch trang 1 (pages=[0])
    await processor.process(
        input_path=str(pdf_path),
        output_path=str(output_path),
        pages=[0],
        dry_run=False,
    )

    assert output_path.exists()
    out_doc = fitz.open(output_path)
    
    assert len(out_doc) == 2
    
    # Trang 1: dịch thành công -> phải có chiều rộng gấp đôi (300 * 2 = 600)
    assert out_doc[0].rect.width == 600
    assert out_doc[0].rect.height == 400
    
    # Trang 2: không dịch -> giữ nguyên chiều rộng (300)
    assert out_doc[1].rect.width == 300
    assert out_doc[1].rect.height == 400
    
    # Kiểm tra xem có chứa cả text gốc và text dịch trên trang 1
    p1_text = out_doc[0].get_text()
    assert "Hello page 1" in p1_text
    assert "Xin chào trang 1" in p1_text

    # Kiểm tra xem trang 2 chỉ chứa text gốc
    p2_text = out_doc[1].get_text()
    assert "Hello page 2" in p2_text
    assert "Xin chào trang 1" not in p2_text
    
    out_doc.close()

