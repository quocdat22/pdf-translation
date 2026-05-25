"""Unit tests cho TextExtractor."""

from __future__ import annotations

import fitz
import pytest

from pdf_translator.extractor import TextExtractor


class MockRow:
    def __init__(self, bbox: tuple[float, float, float, float], cells: list[tuple[float, float, float, float]]) -> None:
        self.bbox = bbox
        self.cells = cells


class MockTable:
    def __init__(self, bbox: tuple[float, float, float, float], rows: list[MockRow], data: list[list[str]]) -> None:
        self.bbox = bbox
        self.rows = rows
        self.data = data

    def extract(self) -> list[list[str]]:
        return self.data


class MockTableFinder:
    def __init__(self, tables: list[MockTable]) -> None:
        self.tables = tables


class MockPage:
    """Mock fitz.Page để test chi tiết các case cấu trúc dict mà không cần tạo file PDF thật."""

    def __init__(self, blocks_data: list[dict], number: int = 0, tables: list[MockTable] | None = None) -> None:
        self.blocks_data = blocks_data
        self.number = number
        self.tables_list = tables or []

    def get_text(self, opt: str, clip: tuple[float, float, float, float] | None = None) -> dict:
        if opt == "dict":
            if clip:
                cx0, cy0, cx1, cy1 = clip
                clipped_blocks = []
                for b in self.blocks_data:
                    bx0, by0, bx1, by1 = b.get("bbox", (0.0, 0.0, 0.0, 0.0))
                    # simple overlap check
                    if max(bx0, cx0) < min(bx1, cx1) and max(by0, cy0) < min(by1, cy1):
                        clipped_blocks.append(b)
                return {"width": 600, "height": 800, "blocks": clipped_blocks}
            return {"width": 600, "height": 800, "blocks": self.blocks_data}
        return {}

    def find_tables(self) -> MockTableFinder:
        return MockTableFinder(self.tables_list)


def test_should_skip_block() -> None:
    """Test hàm _should_skip_block với các chuỗi khác nhau."""
    extractor = TextExtractor()

    # Các block nên bị bỏ qua
    assert extractor._should_skip_block("") is True
    assert extractor._should_skip_block("   ") is True
    assert extractor._should_skip_block("123") is True
    assert extractor._should_skip_block("45.6") is True
    assert extractor._should_skip_block("12/04/2026") is True
    assert extractor._should_skip_block("100%") is True
    assert extractor._should_skip_block("•") is True
    assert extractor._should_skip_block("—") is True
    assert extractor._should_skip_block("*") is True
    assert extractor._should_skip_block("...") is True
    assert extractor._should_skip_block("+1-123-456") is True
    assert extractor._should_skip_block("$250.00") is True

    # Các block không nên bị bỏ qua
    assert extractor._should_skip_block("Hello") is False
    assert extractor._should_skip_block("Chapter 1") is False
    assert extractor._should_skip_block("USD 25") is False
    assert extractor._should_skip_block("A") is False
    assert extractor._should_skip_block("This is paragraph 1.") is False


def test_extract_page_real_pdf() -> None:
    """Test trích xuất từ trang PDF thật được tạo động bằng PyMuPDF."""
    doc = fitz.open()
    page = doc.new_page()

    # Chèn một textbox
    page.insert_textbox(
        fitz.Rect(50, 50, 300, 150),
        "Hello World\nThis is a sample document.",
        fontsize=12,
        fontname="helv",
    )

    extractor = TextExtractor()
    # Mock _is_block_vertical to return False (horizontal text) to allow extraction
    extractor._is_block_vertical = lambda block: False
    blocks = extractor.extract_page(page)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.block_id == 0
    assert "Hello World" in block.text
    assert "This is a sample document." in block.text
    assert block.font_size == pytest.approx(12.0, abs=0.5)
    assert (
        "helv" in block.font_name.lower() or "helvetica" in block.font_name.lower()
    )
    assert block.page_number == 0
    doc.close()



def test_extract_page_type_filtering() -> None:
    """Test bỏ qua block không phải type=0 (hình ảnh, vẽ hình...)."""
    blocks_data = [
        {
            "type": 1,  # Image block
            "bbox": (50, 50, 200, 200),
            "image": b"...",
        },
        {
            "type": 0,  # Text block
            "bbox": (50, 250, 300, 350),
            "lines": [
                {
                    "bbox": (50, 250, 300, 350),
                    "wmode": 0,  # Ngang
                    "spans": [
                        {
                            "text": "Valid text block",
                            "size": 10.0,
                            "font": "Helvetica",
                            "color": 0,
                            "flags": 0,
                            "bbox": (50, 250, 200, 262),
                        }
                    ],
                }
            ],
        },
    ]

    page = MockPage(blocks_data, number=1)
    extractor = TextExtractor()
    blocks = extractor.extract_page(page)

    # Chỉ trích xuất 1 text block, bỏ qua image block
    assert len(blocks) == 1
    assert blocks[0].text == "Valid text block"



def test_extract_page_dominant_style() -> None:
    """Test tìm style dominant khi trong block có nhiều style khác nhau."""
    blocks_data = [
        {
            "type": 0,
            "bbox": (50, 50, 400, 150),
            "lines": [
                {
                    "bbox": (50, 50, 400, 100),
                    "wmode": 0,  # Ngang
                    "spans": [
                        {
                            "text": "Title",  # 5 chars
                            "size": 20.0,
                            "font": "Helvetica-Bold",
                            "color": 16711680,  # Red
                            "flags": 16,  # Bold
                            "bbox": (50, 50, 100, 75),
                        },
                        {
                            "text": " and more descriptive normal text",  # 33 chars
                            "size": 10.0,
                            "font": "Helvetica",
                            "color": 0,  # Black
                            "flags": 0,
                            "bbox": (100, 50, 400, 62),
                        },
                    ],
                }
            ],
        }
    ]

    page = MockPage(blocks_data, number=2)
    extractor = TextExtractor()
    blocks = extractor.extract_page(page)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.text == "Title and more descriptive normal text"
    # Normal text nhiều chữ hơn (33 > 5), nên style của nó phải là dominant
    assert block.font_size == 10.0
    assert block.font_name == "Helvetica"
    assert block.color == 0
    assert block.is_bold is False
    assert block.is_italic is False



def test_extract_page_bold_italic_flags_and_names() -> None:
    """Test phát hiện bold và italic từ flags hoặc từ tên font."""
    blocks_data = [
        {
            "type": 0,
            "bbox": (50, 50, 400, 150),
            "lines": [
                {
                    "wmode": 0,  # Ngang
                    "spans": [
                        {
                            "text": "Bold text",
                            "size": 10.0,
                            "font": "MyCustomFont-Bold",  # Có "bold" trong tên font
                            "color": 0,
                            "flags": 0,  # flag không bật bold
                        }
                    ],
                }
            ],
        },
        {
            "type": 0,
            "bbox": (50, 200, 400, 300),
            "lines": [
                {
                    "wmode": 0,  # Ngang
                    "spans": [
                        {
                            "text": "Italic text",
                            "size": 10.0,
                            "font": "MyCustomFont-Oblique",  # Có "oblique" trong tên font
                            "color": 0,
                            "flags": 2,  # Flag bật italic
                        }
                    ],
                }
            ],
        },
    ]

    # Test Bold từ font name
    page_1 = MockPage([blocks_data[0]], number=0)
    extractor = TextExtractor()
    blocks_1 = extractor.extract_page(page_1)
    assert len(blocks_1) == 1
    assert blocks_1[0].is_bold is True
    assert blocks_1[0].is_italic is False

    # Test Italic từ flag + font name
    page_2 = MockPage([blocks_data[1]], number=1)
    blocks_2 = extractor.extract_page(page_2)
    assert len(blocks_2) == 1
    assert blocks_2[0].is_bold is False
    assert blocks_2[0].is_italic is True


def test_extract_page_horizontal_only_filtering() -> None:
    """Test bộ lọc chỉ trích xuất các block nằm ngang và bỏ qua block thẳng đứng/xoay dọc."""
    blocks_data = [
        {
            "type": 0,
            "bbox": (50, 50, 100, 300),
            "lines": [
                {
                    "bbox": (50, 50, 70, 300),
                    "wmode": 1,  # Dọc
                    "spans": [
                        {"text": "Vertical block", "size": 10.0, "font": "Helvetica", "color": 0}
                    ]
                }
            ]
        },
        {
            "type": 0,
            "bbox": (150, 50, 400, 100),
            "lines": [
                {
                    "bbox": (150, 50, 400, 70),
                    "wmode": 0,  # Ngang
                    "spans": [
                        {"text": "Horizontal block", "size": 10.0, "font": "Helvetica", "color": 0}
                    ]
                }
            ]
        }
    ]

    page = MockPage(blocks_data, number=0)
    extractor = TextExtractor()
    blocks = extractor.extract_page(page)

    # Mặc định phải lọc bỏ block nằm dọc, chỉ lấy block ngang
    assert len(blocks) == 1
    assert blocks[0].text == "Horizontal block"


def test_extract_page_with_tables() -> None:
    """Test trích xuất trang chứa bảng biểu và lọc bỏ các block nằm trùng trong bảng."""
    blocks_data = [
        {
            "type": 0,
            "bbox": (50, 50, 200, 70),  # Ngoài bảng
            "lines": [
                {
                    "wmode": 0,
                    "spans": [{"text": "Outside Text", "size": 11.0, "font": "Helvetica", "color": 0}]
                }
            ]
        },
        {
            "type": 0,
            "bbox": (110, 110, 190, 140),  # Nằm trọn trong ô bảng
            "lines": [
                {
                    "wmode": 0,
                    "spans": [{"text": "Inside Cell Text", "size": 9.0, "font": "Helvetica-Bold", "color": 16777215, "flags": 16}]
                }
            ]
        }
    ]

    mock_row = MockRow(
        bbox=(100, 100, 300, 150),
        cells=[(100, 100, 200, 150), (200, 100, 300, 150)]
    )
    mock_table = MockTable(
        bbox=(100, 100, 300, 150),
        rows=[mock_row],
        data=[["Inside Cell Text", ""]]
    )

    page = MockPage(blocks_data, number=0, tables=[mock_table])
    extractor = TextExtractor()
    blocks = extractor.extract_page(page)

    # Ta mong muốn tìm được:
    # 1. Ô đầu tiên chứa text "Inside Cell Text" (được trích xuất dạng cell)
    # 2. Block ngoài bảng "Outside Text"
    # Ô thứ hai rỗng nên bỏ qua. Block gốc (110, 110, 190, 140) phải bị lọc bỏ để tránh trùng lặp.
    assert len(blocks) == 2
    
    # Kiểm tra ô bảng
    cell_block = [b for b in blocks if b.is_table_cell][0]
    assert cell_block.text == "Inside Cell Text"
    assert cell_block.bbox == (100, 100, 200, 150)
    assert cell_block.is_bold is True
    assert cell_block.font_size == 9.0

    # Kiểm tra block thường ngoài bảng
    normal_block = [b for b in blocks if not b.is_table_cell][0]
    assert normal_block.text == "Outside Text"
    assert normal_block.bbox == (50, 50, 200, 70)

