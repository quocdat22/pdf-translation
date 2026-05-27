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


def test_renderer_get_expanded_rect() -> None:
    """Test helper _get_expanded_rect thực hiện mở rộng bbox chính xác."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    # Khung gốc: chiều rộng = 100, chiều cao = 10 (khá bé so với font size 10)
    bbox = (50, 50, 150, 60)
    font_size = 10.0

    expanded = renderer._get_expanded_rect(bbox, font_size)

    # Chiều rộng phải tăng thêm 5% -> 100 * 1.05 = 105
    assert expanded.width == 105.0
    # Chiều cao ban đầu (10) nhỏ hơn font_size * 1.8 (18) -> phải được tăng lên 18
    assert expanded.height == 18.0
    # Mép trên y0 phải giữ nguyên để bảo toàn vị trí căn lề trên
    assert expanded.y0 == 50.0
    # Mép dưới y1 phải kéo dài xuống dưới -> 50 + 18 = 68
    assert expanded.y1 == 68.0

    # Khung gốc lớn sẵn: chiều rộng = 100, chiều cao = 30 (lớn hơn font_size * 1.8)
    bbox_large = (50, 50, 150, 80)
    expanded_large = renderer._get_expanded_rect(bbox_large, font_size)
    assert expanded_large.width == 105.0
    # Chiều cao ban đầu (30) lớn hơn 18 -> giữ nguyên chiều cao 30
    assert expanded_large.height == 30.0
    assert expanded_large.y1 == 80.0


def test_renderer_render_page_table_cell() -> None:
    """Test quá trình render một block ô bảng (không nới rộng bbox và redact với fill=False)."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    doc = fitz.open()
    page = doc.new_page()

    # Tạo các block giả lập ô bảng
    original_block = TextBlock(
        block_id=0,
        text="Table Cell English",
        bbox=(50, 50, 250, 80),
        font_size=12.0,
        font_name="Helvetica",
        color=(0, 0, 0),
        is_bold=False,
        is_italic=False,
        page_number=0,
        is_table_cell=True,
    )

    translated_block = TranslatedBlock(
        original=original_block,
        translated_text="Dịch ô bảng",
        adjusted_font_size=12.0,
    )

    # Thực hiện render
    renderer.render_page(page, [translated_block], min_font_size=6.0)

    page_text = page.get_text()
    assert "Table Cell English" not in page_text
    assert "Dịch ô bảng" in page_text
    doc.close()


def test_renderer_table_cell_does_not_call_expand(monkeypatch) -> None:
    """Xác nhận _get_expanded_rect không được gọi đối với TextBlock có is_table_cell=True."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    doc = fitz.open()
    page = doc.new_page()

    original_block = TextBlock(
        block_id=0,
        text="Cell Text",
        bbox=(50, 50, 200, 80),
        font_size=10.0,
        font_name="Helvetica",
        color=(0, 0, 0),
        is_bold=False,
        is_italic=False,
        page_number=0,
        is_table_cell=True,
    )

    translated_block = TranslatedBlock(
        original=original_block,
        translated_text="Text dịch",
        adjusted_font_size=10.0,
    )

    called = False
    def mock_get_expanded_rect(bbox, font_size):
        nonlocal called
        called = True
        return fitz.Rect(bbox)

    monkeypatch.setattr(renderer, "_get_expanded_rect", mock_get_expanded_rect)
    renderer.render_page(page, [translated_block])

    assert called is False, "_get_expanded_rect should not be called for table cells"
    doc.close()


def test_renderer_redaction_transparency_and_parameters(monkeypatch) -> None:
    """Test renderer thực hiện che chữ trong suốt và truyền đúng các flag để giữ hình ảnh/nét vẽ."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    doc = fitz.open()
    page = doc.new_page()

    original_block = TextBlock(
        block_id=0,
        text="Normal Text Block",
        bbox=(50, 50, 200, 80),
        font_size=10.0,
        font_name="Helvetica",
        color=(0, 0, 0),
        is_bold=False,
        is_italic=False,
        page_number=0,
        is_table_cell=False,
    )

    translated_block = TranslatedBlock(
        original=original_block,
        translated_text="Text đã dịch",
        adjusted_font_size=10.0,
    )

    # Mock add_redact_annot để kiểm tra fill=False
    add_redact_called = []
    original_add_redact_annot = page.add_redact_annot
    def mock_add_redact_annot(rect, fill=None, **kwargs):
        add_redact_called.append((rect, fill))
        return original_add_redact_annot(rect, fill=fill, **kwargs)

    # Mock apply_redactions để kiểm tra tham số images và graphics
    apply_redacts_called = []
    original_apply_redactions = page.apply_redactions
    def mock_apply_redactions(images=None, graphics=None, **kwargs):
        apply_redacts_called.append((images, graphics))
        return original_apply_redactions(images=images, graphics=graphics, **kwargs)

    monkeypatch.setattr(page, "add_redact_annot", mock_add_redact_annot)
    monkeypatch.setattr(page, "apply_redactions", mock_apply_redactions)

    renderer.render_page(page, [translated_block])

    # Kiểm tra add_redact_annot được gọi với fill=False cho block thường
    assert len(add_redact_called) == 1
    assert add_redact_called[0][1] is False

    # Kiểm tra apply_redactions được gọi với đúng flag bảo toàn
    assert len(apply_redacts_called) == 1
    assert apply_redacts_called[0][0] == fitz.PDF_REDACT_IMAGE_NONE
    assert apply_redacts_called[0][1] == fitz.PDF_REDACT_LINE_ART_NONE

    doc.close()


def test_renderer_alignment_and_font_family(monkeypatch) -> None:
    """Test renderer thực hiện render đúng căn lề (align) và họ font (font_family)."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    doc = fitz.open()
    page = doc.new_page()

    # Căn lề phải (align=2), Serif font
    original_block = TextBlock(
        block_id=0,
        text="Serif Text Block",
        bbox=(50, 50, 200, 80),
        font_size=10.0,
        font_name="TimesNewRoman",
        color=(0, 0, 0),
        is_bold=True,
        is_italic=False,
        page_number=0,
        is_table_cell=False,
        align=2,
        font_family="serif",
    )

    translated_block = TranslatedBlock(
        original=original_block,
        translated_text="Text dịch Serif căn phải",
        adjusted_font_size=10.0,
    )

    # Mock insert_textbox để kiểm tra align và fontname
    insert_textbox_called = []
    original_insert_textbox = page.insert_textbox
    def mock_insert_textbox(rect, text, fontsize=None, fontname=None, color=None, align=0, **kwargs):
        insert_textbox_called.append((rect, text, fontsize, fontname, color, align))
        return original_insert_textbox(rect, text, fontsize=fontsize, fontname=fontname, color=color, align=align, **kwargs)

    # Mock register_font trong font_manager để xem family nào được đăng ký
    register_font_called = []
    original_register_font = fm.register_font
    def mock_register_font(page_arg, family="sans", is_bold=False, is_italic=False):
        register_font_called.append((family, is_bold, is_italic))
        return original_register_font(page_arg, family=family, is_bold=is_bold, is_italic=is_italic)

    monkeypatch.setattr(page, "insert_textbox", mock_insert_textbox)
    monkeypatch.setattr(fm, "register_font", mock_register_font)

    renderer.render_page(page, [translated_block])

    # Kiểm tra xem register_font được gọi với họ serif
    assert len(register_font_called) > 0
    # Cả temp page và real page đều được đăng ký
    assert any(family == "serif" for family, _, _ in register_font_called)

    # Kiểm tra xem insert_textbox nhận được align=2 và fontname tương ứng SerifBold
    assert len(insert_textbox_called) == 1
    assert insert_textbox_called[0][3] in ("TimesNewRomanBold", "NotoSansBold")
    assert insert_textbox_called[0][5] == 2  # align = 2 (Right)

    doc.close()


def test_renderer_expand_rect_collision_right() -> None:
    """Test mở rộng sang phải bị giới hạn bởi block khác bên phải (chừa cushion 2pt)."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    # Block hiện tại ở (50, 50, 150, 70), align = 0
    cur_block = TranslatedBlock(
        original=TextBlock(
            block_id=0,
            text="Current Block",
            bbox=(50.0, 50.0, 150.0, 70.0),
            font_size=10.0,
            font_name="Helvetica",
            color=(0, 0, 0),
            align=0,
        ),
        translated_text="Dịch",
        adjusted_font_size=10.0,
    )

    # Block cản trở bên phải ở (200, 50, 300, 70)
    other_block = TranslatedBlock(
        original=TextBlock(
            block_id=1,
            text="Other Block",
            bbox=(200.0, 50.0, 300.0, 70.0),
            font_size=10.0,
            font_name="Helvetica",
            color=(0, 0, 0),
        ),
        translated_text="Khác",
        adjusted_font_size=10.0,
    )

    all_blocks = [cur_block, other_block]
    page_rect = fitz.Rect(0, 0, 500, 500)

    expanded = renderer._get_expanded_rect(
        cur_block.original.bbox,
        cur_block.original.font_size,
        all_blocks=all_blocks,
        current_block=cur_block,
        page_rect=page_rect,
    )

    # Trục X: 50 -> 200 - 2.0 (cushion) = 198.0
    assert expanded.x0 == 50.0
    assert expanded.x1 == 198.0
    # Không được mở rộng dọc vì mở rộng ngang thành công
    assert expanded.y0 == 50.0
    assert expanded.y1 == 70.0


def test_renderer_expand_rect_collision_left() -> None:
    """Test mở rộng sang trái (do align=2) bị giới hạn bởi block khác bên trái."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    # Block hiện tại ở (150, 50, 250, 70), align = 2 (Right align)
    cur_block = TranslatedBlock(
        original=TextBlock(
            block_id=0,
            text="Current Block",
            bbox=(150.0, 50.0, 250.0, 70.0),
            font_size=10.0,
            font_name="Helvetica",
            color=(0, 0, 0),
            align=2,
        ),
        translated_text="Dịch",
        adjusted_font_size=10.0,
    )

    # Block cản trở bên trái ở (50, 50, 100, 70)
    other_block = TranslatedBlock(
        original=TextBlock(
            block_id=1,
            text="Other Block",
            bbox=(50.0, 50.0, 100.0, 70.0),
            font_size=10.0,
            font_name="Helvetica",
            color=(0, 0, 0),
        ),
        translated_text="Khác",
        adjusted_font_size=10.0,
    )

    all_blocks = [cur_block, other_block]
    page_rect = fitz.Rect(0, 0, 500, 500)

    expanded = renderer._get_expanded_rect(
        cur_block.original.bbox,
        cur_block.original.font_size,
        all_blocks=all_blocks,
        current_block=cur_block,
        page_rect=page_rect,
    )

    # Trục X: 100 + 2.0 (cushion) = 102.0 -> 250
    assert expanded.x0 == 102.0
    assert expanded.x1 == 250.0
    # Không mở rộng dọc
    assert expanded.y0 == 50.0
    assert expanded.y1 == 70.0


def test_renderer_expand_rect_collision_vertical() -> None:
    """Test fallback mở rộng dọc khi hướng ngang bị chặn đứng hoàn toàn."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    # Block hiện tại ở (50, 50, 150, 70), align = 0
    cur_block = TranslatedBlock(
        original=TextBlock(
            block_id=0,
            text="Current Block",
            bbox=(50.0, 50.0, 150.0, 70.0),
            font_size=10.0,
            font_name="Helvetica",
            color=(0, 0, 0),
            align=0,
        ),
        translated_text="Dịch",
        adjusted_font_size=10.0,
    )

    # Block cản trở bên phải sát sạt ở (151, 50, 200, 70) -> Không mở rộng ngang được (> 0pt) vì cushion = 2
    other_right = TranslatedBlock(
        original=TextBlock(
            block_id=1,
            text="Other Right",
            bbox=(151.0, 50.0, 200.0, 70.0),
            font_size=10.0,
            font_name="Helvetica",
            color=(0, 0, 0),
        ),
        translated_text="Khác",
        adjusted_font_size=10.0,
    )

    # Block cản trở bên dưới ở (50, 100, 150, 120)
    other_bottom = TranslatedBlock(
        original=TextBlock(
            block_id=2,
            text="Other Bottom",
            bbox=(50.0, 100.0, 150.0, 120.0),
            font_size=10.0,
            font_name="Helvetica",
            color=(0, 0, 0),
        ),
        translated_text="Khác",
        adjusted_font_size=10.0,
    )

    all_blocks = [cur_block, other_right, other_bottom]
    page_rect = fitz.Rect(0, 0, 500, 500)

    expanded = renderer._get_expanded_rect(
        cur_block.original.bbox,
        20.0,  # font_size = 20.0, so target_h = 36.0, target_y1 = 50 + 36 = 86
        all_blocks=all_blocks,
        current_block=cur_block,
        page_rect=page_rect,
    )

    # Trục X giữ nguyên
    assert expanded.x0 == 50.0
    assert expanded.x1 == 150.0
    # Mở rộng dọc: max_y1 = 100 - 2.0 = 98.0. Target bottom = 86.0.
    # Vì 86.0 < 98.0 nên expanded.y1 phải là 86.0.
    assert expanded.y0 == 50.0
    assert expanded.y1 == 86.0


def test_renderer_expand_rect_boundary() -> None:
    """Test mở rộng sang phải bị giới hạn bởi mép trang (page boundary)."""
    fm = FontManager()
    renderer = TextRenderer(fm)

    # Block hiện tại: (400, 50, 450, 70), align = 0
    cur_block = TranslatedBlock(
        original=TextBlock(
            block_id=0,
            text="Current Block",
            bbox=(400.0, 50.0, 450.0, 70.0),
            font_size=10.0,
            font_name="Helvetica",
            color=(0, 0, 0),
            align=0,
        ),
        translated_text="Dịch",
        adjusted_font_size=10.0,
    )

    # Block thứ hai xác định lề phải chính của cột nội dung là 20pt (x1 = 480.0, page width = 500)
    margin_block = TranslatedBlock(
        original=TextBlock(
            block_id=1,
            text="Margin Definer Block",
            bbox=(100.0, 100.0, 480.0, 120.0),
            font_size=10.0,
            font_name="Helvetica",
            color=(0, 0, 0),
        ),
        translated_text="Lề",
        adjusted_font_size=10.0,
    )

    all_blocks = [cur_block, margin_block]
    # Trang rộng 500
    page_rect = fitz.Rect(0, 0, 500, 500)

    expanded = renderer._get_expanded_rect(
        cur_block.original.bbox,
        cur_block.original.font_size,
        all_blocks=all_blocks,
        current_block=cur_block,
        page_rect=page_rect,
    )

    # Trục X: Cần được giới hạn bởi max_allowed_x1 = 480.0. Với cushion 2.0pt -> 480 - 2.0 = 478.0
    assert expanded.x0 == 400.0
    assert expanded.x1 == 478.0
    # Không mở rộng dọc
    assert expanded.y0 == 50.0
    assert expanded.y1 == 70.0





