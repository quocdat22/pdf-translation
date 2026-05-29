from unittest.mock import MagicMock
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
        self.rect = MagicMock()
        self.rect.width = 600
        self.rect.height = 800

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


def test_should_skip_block_math() -> None:
    """Test hàm _should_skip_block với các khối ký hiệu và biểu thức toán học."""
    extractor = TextExtractor()

    # Khối chứa công thức toán
    assert extractor._should_skip_block("h1 = a[θ10 + θ11x1 + θ12x2]", ["CMMI10"]) is True
    assert extractor._should_skip_block("h1 = a[θ10 + θ11x1 + θ12x2]") is True  # Vẫn bỏ qua ngay cả khi không truyền font nhờ ký tự toán/greek
    
    # Biến toán học đơn lẻ dùng font toán
    assert extractor._should_skip_block("x", ["CMMI10"]) is True
    # Biến toán học đơn lẻ dùng font thường thì không bỏ qua (chờ check Latin ở bước sau)
    assert extractor._should_skip_block("x", ["Helvetica"]) is False
    
    # Phép tính toán học đơn giản
    assert extractor._should_skip_block("1 + 1 = 2") is True
    assert extractor._should_skip_block("f(x, y) = x^2 + y^2") is True
    assert extractor._should_skip_block("sin(x) + cos(y) = 1") is True
    
    # Các câu/từ thông thường chứa ký tự toán học (không được bỏ qua)
    assert extractor._should_skip_block("Let x = 1", ["Helvetica"]) is False
    assert extractor._should_skip_block("The temperature is T > 30°C", ["Helvetica"]) is False
    assert extractor._should_skip_block("USD 25") is False


def test_extractor_detect_alignment_and_font_family() -> None:
    """Test tính năng nhận diện alignment và phân loại font family."""
    extractor = TextExtractor()

    # 1. Test phân loại font family
    assert extractor._classify_font_family("TimesNewRoman-Bold") == "serif"
    assert extractor._classify_font_family("LiberationSerif") == "serif"
    assert extractor._classify_font_family("Courier-Oblique") == "mono"
    assert extractor._classify_font_family("DejaVuSansMono") == "mono"
    assert extractor._classify_font_family("Helvetica") == "sans"
    assert extractor._classify_font_family("NotoSans-Regular") == "sans"

    # 2. Test nhận diện alignment trong ô bảng
    # Center trong ô
    cell_bbox = (100, 100, 200, 150)  # width = 100, center = 150
    text_bbox_center = (130, 110, 170, 140)  # center = 150, margins = (30, 30)
    assert extractor._detect_alignment(text_bbox_center, [], 600, cell_bbox) == 1

    # Right trong ô
    text_bbox_right = (160, 110, 198, 140)  # right margin = 2
    assert extractor._detect_alignment(text_bbox_right, [], 600, cell_bbox) == 2

    # Left trong ô
    text_bbox_left = (102, 110, 140, 140)  # left margin = 2, right margin = 60
    assert extractor._detect_alignment(text_bbox_left, [], 600, cell_bbox) == 0

    # 3. Test nhận diện alignment cho block nhiều dòng
    # Căn giữa (center)
    lines_center = [
        {"bbox": (130, 100, 170, 120)},
        {"bbox": (120, 120, 180, 140)},
    ]
    block_bbox_center = (120, 100, 180, 140)  # width = 60, center = 150
    assert extractor._detect_alignment(block_bbox_center, lines_center, 600) == 1

    # Căn phải (right)
    lines_right = [
        {"bbox": (140, 100, 180, 120)},
        {"bbox": (120, 120, 180, 140)},
    ]
    block_bbox_right = (120, 100, 180, 140)  # lines end at 180
    assert extractor._detect_alignment(block_bbox_right, lines_right, 600) == 2

    # Căn đều hai bên (justify) -> fallback về 0 (Left)
    lines_justify = [
        {"bbox": (100.0, 100.0, 300.0, 120.0)},
        {"bbox": (100.0, 120.0, 300.0, 140.0)},
        {"bbox": (100.0, 140.0, 200.0, 160.0)},  # dòng cuối thụt lề
    ]
    block_bbox_justify = (100.0, 100.0, 300.0, 160.0)  # width = 200.0
    assert extractor._detect_alignment(block_bbox_justify, lines_justify, 600) == 0

    # 4. Test nhận diện alignment cho block 1 dòng
    # Căn phải sát lề trang
    line_page_right = [{"bbox": (500, 100, 580, 120)}]
    assert extractor._detect_alignment((500, 100, 580, 120), line_page_right, 600) == 2

    # Căn giữa trang
    line_page_center = [{"bbox": (250, 100, 350, 120)}]
    assert extractor._detect_alignment((250, 100, 350, 120), line_page_center, 600) == 1

    # 5. Test các trường hợp đặc biệt đợt cải thiện căn lề 2
    # 5.1. Test LEFT flush override RIGHT (Bug 1 của book1.pdf)
    # 8 dòng, tất cả left_deltas = 0 (perfect flush left), right_deltas dao động nhẹ (max_right_delta = 16.9 < block_w * 0.05 = 21.5)
    # block_w = 430.0
    lines_bug1 = [
        {"bbox": (100.0, 100.0, 513.1, 115.0)}, # L0: left=100.0, right=513.1 -> right_delta = 16.9
        {"bbox": (100.0, 115.0, 520.6, 130.0)}, # L1: right_delta = 9.4
        {"bbox": (100.0, 130.0, 520.9, 145.0)}, # L2: right_delta = 9.1
        {"bbox": (100.0, 145.0, 528.3, 160.0)}, # L3: right_delta = 1.7
        {"bbox": (100.0, 160.0, 518.2, 175.0)}, # L4: right_delta = 11.8
        {"bbox": (100.0, 175.0, 530.0, 190.0)}, # L5: right_delta = 0.0
        {"bbox": (100.0, 190.0, 518.5, 205.0)}, # L6: right_delta = 11.5
        {"bbox": (100.0, 205.0, 460.0, 220.0)}, # L7 (dòng cuối): right_delta = 70.0
    ]
    block_bbox_bug1 = (100.0, 100.0, 530.0, 220.0) # width = 430.0
    assert extractor._detect_alignment(block_bbox_bug1, lines_bug1, 600) == 0 # Phải là LEFT (0)

    # 5.2. Test LEFT flush override CENTER trong block hẹp (Bug 2 của book1.pdf)
    # 9 dòng, left_deltas = 0, block_w = 142.6
    # max_center_delta của body lines < block_w * 0.08 (11.4)
    lines_bug2 = [
        {"bbox": (100.0, 100.0, 224.7, 115.0)},
        {"bbox": (100.0, 115.0, 230.3, 130.0)},
        {"bbox": (100.0, 130.0, 238.3, 145.0)},
        {"bbox": (100.0, 145.0, 221.3, 160.0)},
        {"bbox": (100.0, 160.0, 234.4, 175.0)},
        {"bbox": (100.0, 175.0, 238.7, 190.0)},
        {"bbox": (100.0, 190.0, 242.6, 205.0)},
        {"bbox": (100.0, 205.0, 234.9, 220.0)},
        {"bbox": (100.0, 220.0, 230.7, 235.0)},
    ]
    block_bbox_bug2 = (100.0, 100.0, 242.6, 235.0) # width = 142.6
    assert extractor._detect_alignment(block_bbox_bug2, lines_bug2, 600) == 0 # Phải là LEFT (0)

    # 5.3. Test bullet point indent (Bug 3 của book1.pdf)
    # 2 dòng: L0 left_delta = 0, L1 left_delta = 9.0 (thụt lề sau bullet), block_w = 160.0
    lines_bug3 = [
        {"bbox": (100.0, 100.0, 256.9, 120.0)}, # L0: left=100.0, right=256.9 -> left_delta=0, right_delta=3.1
        {"bbox": (109.0, 120.0, 260.0, 140.0)}, # L1: left=109.0, right=260.0 -> left_delta=9.0, right_delta=0.0
    ]
    block_bbox_bug3 = (100.0, 100.0, 260.0, 140.0) # width = 160.0
    assert extractor._detect_alignment(block_bbox_bug3, lines_bug3, 600) == 0 # Phải là LEFT (0)

    # 5.4. Test right-aligned vẫn hoạt động bình thường (ragged left, flush right)
    # 3 dòng, left_deltas = [20.0, 10.0, 0.0], right_deltas = [0.0, 0.0, 0.0]
    lines_right_align = [
        {"bbox": (120.0, 100.0, 200.0, 120.0)}, # right = 200
        {"bbox": (110.0, 120.0, 200.0, 140.0)}, # right = 200
        {"bbox": (100.0, 140.0, 200.0, 160.0)}, # right = 200
    ]
    block_bbox_right_align = (100.0, 100.0, 200.0, 160.0) # width = 100.0
    assert extractor._detect_alignment(block_bbox_right_align, lines_right_align, 600) == 2 # Phải là RIGHT (2)

    # 5.5. Test thụt lề dòng đầu (First-line indent) - 3 dòng
    # L0 thụt lề 15pt, L1, L2 sát lề trái, L2 là dòng cuối ngắn. L0, L1 sát lề phải.
    lines_first_line_indent_3lines = [
        {"bbox": (115.0, 100.0, 300.0, 120.0)}, # left_delta = 15.0, right_delta = 0.0
        {"bbox": (100.0, 120.0, 300.0, 140.0)}, # left_delta = 0.0, right_delta = 0.0
        {"bbox": (100.0, 140.0, 200.0, 160.0)}, # left_delta = 0.0, right_delta = 100.0 (dòng cuối ngắn)
    ]
    block_bbox_first_line_indent_3lines = (100.0, 100.0, 300.0, 160.0) # width = 200.0
    assert extractor._detect_alignment(block_bbox_first_line_indent_3lines, lines_first_line_indent_3lines, 600) == 0 # Phải là LEFT (0)

    # 5.6. Test thụt lề dòng đầu (First-line indent) - 2 dòng (dòng cuối ngắn)
    # L0 thụt lề 20pt, L1 sát lề trái và kết thúc sớm (dòng cuối ngắn)
    lines_first_line_indent_2lines = [
        {"bbox": (120.0, 100.0, 300.0, 120.0)}, # left_delta = 20.0, right_delta = 0.0
        {"bbox": (100.0, 120.0, 220.0, 140.0)}, # left_delta = 0.0, right_delta = 80.0
    ]
    block_bbox_first_line_indent_2lines = (100.0, 100.0, 300.0, 140.0) # width = 200.0
    assert extractor._detect_alignment(block_bbox_first_line_indent_2lines, lines_first_line_indent_2lines, 600) == 0 # Phải là LEFT (0)


def test_extractor_split_non_paragraph_block() -> None:
    """Test tính năng tự động chia nhỏ block thành các dòng độc lập khi block không phải paragraph (như tên tác giả/email)."""
    # 1. Mock block chứa tên và email (nên bị chia đôi)
    split_block_data = {
        "type": 0,
        "bbox": (150.0, 100.0, 300.0, 140.0), # width = 150.0
        "lines": [
            {
                "bbox": (200.0, 100.0, 270.0, 120.0), # width = 70.0 (70/150 = 46.7% < 70% -> split)
                "wmode": 0,
                "spans": [{"text": "Author Name", "size": 10.0, "font": "Helvetica", "color": 0, "flags": 0}],
            },
            {
                "bbox": (150.0, 120.0, 300.0, 140.0), # line cuối (email)
                "wmode": 0,
                "spans": [{"text": "author@email.com", "size": 9.0, "font": "Courier", "color": 0, "flags": 0}],
            }
        ]
    }

    # 2. Mock block chứa đoạn văn thường (không bị chia đôi)
    paragraph_block_data = {
        "type": 0,
        "bbox": (100.0, 200.0, 300.0, 240.0), # width = 200.0
        "lines": [
            {
                "bbox": (100.0, 200.0, 300.0, 220.0), # width = 200.0 (100% -> no split)
                "wmode": 0,
                "spans": [{"text": "This is line one of a normal paragraph.", "size": 11.0, "font": "Helvetica", "color": 0, "flags": 0}],
            },
            {
                "bbox": (100.0, 220.0, 250.0, 240.0), # line cuối (thụt lề tùy ý)
                "wmode": 0,
                "spans": [{"text": "This is line two.", "size": 11.0, "font": "Helvetica", "color": 0, "flags": 0}],
            }
        ]
    }

    page = MockPage([split_block_data, paragraph_block_data], number=0)
    extractor = TextExtractor()
    blocks = extractor.extract_page(page)

    # Mong muốn:
    # - Block 1 bị tách làm 2 TextBlocks riêng
    # - Block 2 giữ nguyên là 1 TextBlock duy nhất
    # -> Tổng cộng 3 TextBlocks
    assert len(blocks) == 3

    # Kiểm tra block tên (bị split -> group chỉ có 1 dòng)
    b0 = blocks[0]
    assert b0.text == "Author Name"
    assert b0.bbox == (200.0, 100.0, 270.0, 120.0)
    assert b0.is_table_cell is False
    assert b0.line_count == 1

    # Kiểm tra block email (bị split -> group chỉ có 1 dòng)
    b1 = blocks[1]
    assert b1.text == "author@email.com"
    assert b1.bbox == (150.0, 120.0, 300.0, 140.0)
    assert b1.line_count == 1

    # Kiểm tra block đoạn văn (không bị split -> group có 2 dòng)
    b2 = blocks[2]
    assert "normal paragraph" in b2.text
    assert b2.bbox == (100.0, 200.0, 300.0, 240.0)
    assert b2.line_count == 2



