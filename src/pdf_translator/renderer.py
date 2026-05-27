"""Text Renderer — xóa text gốc và chèn text dịch vào đúng vị trí trên PDF.

Thực hiện co giãn font chữ (auto-shrink) để tránh tràn khung (overflow)
và giữ nguyên định dạng, bố cục của trang gốc.
"""

from __future__ import annotations

import fitz  # PyMuPDF

from pdf_translator.models import TranslatedBlock
from pdf_translator.font_manager import FontManager
from pdf_translator.logger import get_logger

logger = get_logger(__name__)


class TextRenderer:
    """Xóa text gốc và chèn text dịch vào đúng vị trí trên PDF."""

    def __init__(self, font_manager: FontManager) -> None:
        """Khởi tạo TextRenderer.

        Args:
            font_manager: Đối tượng FontManager quản lý font Noto Sans.
        """
        self.font_manager = font_manager

    def render_page(
        self,
        page: fitz.Page,
        translated_blocks: list[TranslatedBlock],
        min_font_size: float = 6.0,
    ) -> None:
        """Render text dịch lên một trang PDF.

        Quy trình:
        1. Tính toán font size tối ưu (auto-shrink) cho từng block bằng trang nháp.
        2. Xóa text gốc bằng redaction (phủ nền trắng để che).
        3. Chèn text dịch vào đúng bbox gốc với font size đã điều chỉnh.

        Args:
            page: Trang PDF thật cần chỉnh sửa (fitz.Page).
            translated_blocks: Danh sách các TranslatedBlock đã được dịch.
            min_font_size: Kích thước font tối thiểu khi co giãn (pt).
        """
        if not translated_blocks:
            return

        # 1. Tính toán trước font size phù hợp trên một trang nháp (temporary page)
        temp_doc = fitz.open()
        try:
            # Tạo trang nháp có cùng kích thước với trang thật
            temp_page = temp_doc.new_page(width=page.rect.width, height=page.rect.height)
            registered_temp_fonts: set[str] = set()

            for block in translated_blocks:
                if not block.translated_text:
                    continue

                # Xác định variant font cần dùng và đăng ký trên temp page (nếu chưa có)
                font_key = (block.original.font_family, block.original.is_bold, block.original.is_italic)
                font_name = self.font_manager.FONT_NAMES[font_key]
                if font_name not in registered_temp_fonts:
                    self.font_manager.register_font(
                        temp_page,
                        family=block.original.font_family,
                        is_bold=block.original.is_bold,
                        is_italic=block.original.is_italic,
                    )
                    registered_temp_fonts.add(font_name)

                # Tính font size vừa vặn nhất
                if block.original.is_table_cell:
                    rect_to_use = fitz.Rect(block.original.bbox)
                    cell_min_font_size = min(4.0, min_font_size)
                else:
                    rect_to_use = self._get_expanded_rect(
                        block.original.bbox,
                        block.original.font_size,
                        all_blocks=translated_blocks,
                        current_block=block,
                        page_rect=page.rect,
                    )
                    cell_min_font_size = min_font_size

                adjusted_size = self._calculate_font_size(
                    temp_page=temp_page,
                    text=block.translated_text,
                    bbox=tuple(rect_to_use),
                    original_size=block.original.font_size,
                    min_size=cell_min_font_size,
                    font_name=font_name,
                    align=block.original.align,
                )
                block.adjusted_font_size = adjusted_size
        finally:
            temp_doc.close()

        # 2. Thực hiện xóa văn bản gốc trên trang thật
        self._redact_original_text(page, translated_blocks)

        # 3. Chèn văn bản đã dịch lên trang thật
        self._insert_translated_text(page, translated_blocks)

    def _redact_original_text(
        self, page: fitz.Page, blocks: list[TranslatedBlock]
    ) -> None:
        """Xóa văn bản gốc bằng redaction annotation (phủ nền trắng hoặc để trong suốt)."""
        for block in blocks:
            if not block.original.text.strip():
                continue
            rect = fitz.Rect(block.original.bbox)
            # Dùng fill=False (trong suốt) cho mọi block để giữ nguyên màu nền/đồ họa/hình ảnh
            page.add_redact_annot(rect, fill=False)

        # Chỉ xóa text, giữ nguyên hình ảnh (images) và đồ họa dạng vector (graphics/line art)
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_NONE
        )
        # Chuẩn hóa và tối ưu hóa nội dung trang sau khi xóa
        page.clean_contents()

    def _insert_translated_text(
        self, page: fitz.Page, blocks: list[TranslatedBlock]
    ) -> None:
        """Chèn text dịch vào đúng các vị trí bbox gốc."""
        registered_real_fonts: set[str] = set()

        for block in blocks:
            if not block.translated_text:
                continue

            if block.original.is_table_cell:
                rect = fitz.Rect(block.original.bbox)
            else:
                rect = self._get_expanded_rect(
                    block.original.bbox,
                    block.original.font_size,
                    all_blocks=blocks,
                    current_block=block,
                    page_rect=page.rect,
                )
            font_key = (block.original.font_family, block.original.is_bold, block.original.is_italic)
            font_name = self.font_manager.FONT_NAMES[font_key]

            # Đăng ký font trên trang thật (nếu chưa có)
            if font_name not in registered_real_fonts:
                self.font_manager.register_font(
                    page,
                    family=block.original.font_family,
                    is_bold=block.original.is_bold,
                    is_italic=block.original.is_italic,
                )
                registered_real_fonts.add(font_name)

            color = block.original.color_rgb

            # Sử dụng đúng căn lề của văn bản gốc (align=block.original.align)
            page.insert_textbox(
                rect,
                block.translated_text,
                fontsize=block.adjusted_font_size,
                fontname=font_name,
                color=color,
                align=block.original.align,
            )

    def _get_expanded_rect(
        self,
        bbox: tuple[float, float, float, float],
        font_size: float,
        all_blocks: list[TranslatedBlock] | None = None,
        current_block: TranslatedBlock | None = None,
        page_rect: fitz.Rect | None = None,
    ) -> fitz.Rect:
        """Tạo bounding box mở rộng để tránh việc co chữ quá mức hoặc mất chữ do giới hạn dòng.

        Quy trình:
        1. Nếu không có đủ dữ liệu ngữ cảnh (all_blocks hoặc page_rect), dùng logic mở rộng mặc định cũ.
        2. Xác định hướng mở rộng ngang dựa vào align:
           - align == 2 (phải): mở rộng sang trái
           - align != 2 (trái/giữa): mở rộng sang phải
        3. Thử mở rộng ngang tối đa đến phần tử gần nhất (trừ đệm 2pt) hoặc mép trang.
           Nếu mở rộng ngang được > 0pt thì chỉ mở rộng ngang và trả về.
        4. Nếu không mở rộng ngang được, fallback sang mở rộng dọc xuống dưới:
           - Chiều cao mục tiêu là max(h, font_size * 1.8)
           - Giới hạn bởi phần tử bên dưới (trừ đệm 2pt) hoặc mép dưới trang.
           - Trả về bbox mở rộng dọc.
        5. Nếu không thể mở rộng dọc luôn, trả về bbox gốc.
        """
        x0, y0, x1, y1 = bbox
        w = x1 - x0
        h = y1 - y0

        # Fallback về logic cũ nếu thiếu thông tin
        if all_blocks is None or page_rect is None:
            new_h = max(h, font_size * 1.8)
            new_w = w + (w * 0.05)
            return fitz.Rect(x0, y0, x0 + new_w, y0 + new_h)

        # Lấy danh sách các bbox của những block khác trên trang
        other_bboxes = []
        for block in all_blocks:
            if current_block and block == current_block:
                continue
            # Chỉ lấy các block có text để tránh va chạm với block rỗng/bỏ qua
            if block.original and block.original.text.strip():
                other_bboxes.append(block.original.bbox)

        # Lấy thông số căn lề từ current_block
        align = current_block.original.align if current_block and current_block.original else 0

        # Mép trang tuyệt đối
        page_x0 = page_rect.x0
        page_y0 = page_rect.y0
        page_x1 = page_rect.x1
        page_y1 = page_rect.y1

        # Ước lượng lề phải và lề trái thực tế của cột nội dung chính (mặc định 54pt ~ 0.75 inch)
        original_right_margin = 54.0
        original_left_margin = 54.0

        if all_blocks:
            right_margins = []
            left_margins = []
            page_w = page_rect.width
            page_h = page_rect.height
            for block in all_blocks:
                if not block.original or not block.original.text.strip():
                    continue
                # Bỏ qua header/footer ở 10% top/bottom
                ob_y0 = block.original.bbox[1]
                ob_y1 = block.original.bbox[3]
                if ob_y0 < page_h * 0.1 or ob_y1 > page_h * 0.9:
                    continue
                # Bỏ qua các block quá nhỏ
                ox0, _, ox1, _ = block.original.bbox
                if (ox1 - ox0) < 30.0:
                    continue
                
                if ox1 > page_w / 2:
                    right_margins.append(page_x1 - ox1)
                if ox0 < page_w / 2:
                    left_margins.append(ox0 - page_x0)
            
            if right_margins:
                original_right_margin = max(10.0, min(right_margins))
            if left_margins:
                original_left_margin = max(10.0, min(left_margins))

        # Sử dụng biên cột nội dung làm giới hạn mở rộng tối đa thay vì mép trang tuyệt đối
        max_allowed_x1 = page_x1 - original_right_margin
        min_allowed_x0 = page_x0 + original_left_margin

        # Khoảng đệm an toàn
        cushion = 2.0

        if align == 2:
            # Hướng ngang: Mở rộng sang TRÁI
            # Tìm các phần tử chồng lấn dọc và nằm bên trái
            left_boundaries = [min_allowed_x0]
            for ob in other_bboxes:
                ox0, oy0, ox1, oy1 = ob
                # Chồng lấn dọc
                if max(y0, oy0) < min(y1, oy1):
                    # Nằm bên trái
                    if ox1 <= x0:
                        left_boundaries.append(ox1)
            
            max_left = max(left_boundaries)
            # Giới hạn bên trái mới, có chừa đệm cushion
            new_x0 = max_left + cushion
            if new_x0 < x0:
                # Thành công mở rộng sang trái
                return fitz.Rect(new_x0, y0, x1, y1)
        elif align == 1:
            # Hướng ngang: Mở rộng ĐỐI XỨNG sang cả 2 bên để giữ nguyên tâm
            # 1. Tìm khoảng trống tối đa bên trái
            left_boundaries = [min_allowed_x0]
            for ob in other_bboxes:
                ox0, oy0, ox1, oy1 = ob
                if max(y0, oy0) < min(y1, oy1):
                    if ox1 <= x0:
                        left_boundaries.append(ox1)
            max_left = max(left_boundaries)
            max_left_expansion = max(0.0, x0 - (max_left + cushion))

            # 2. Tìm khoảng trống tối đa bên phải
            right_boundaries = [max_allowed_x1]
            for ob in other_bboxes:
                ox0, oy0, ox1, oy1 = ob
                if max(y0, oy0) < min(y1, oy1):
                    if ox0 >= x1:
                        right_boundaries.append(ox0)
            min_right = min(right_boundaries)
            max_right_expansion = max(0.0, (min_right - cushion) - x1)

            # 3. Chọn lượng mở rộng đối xứng nhỏ nhất giữa 2 bên
            symmetric_dx = min(max_left_expansion, max_right_expansion)
            if symmetric_dx > 0.0:
                return fitz.Rect(x0 - symmetric_dx, y0, x1 + symmetric_dx, y1)
        else:
            # Hướng ngang: Mở rộng sang PHẢI
            # Tìm các phần tử chồng lấn dọc và nằm bên phải
            right_boundaries = [max_allowed_x1]
            for ob in other_bboxes:
                ox0, oy0, ox1, oy1 = ob
                # Chồng lấn dọc
                if max(y0, oy0) < min(y1, oy1):
                    # Nằm bên phải
                    if ox0 >= x1:
                        right_boundaries.append(ox0)
            
            min_right = min(right_boundaries)
            # Giới hạn bên phải mới, có chừa đệm cushion
            new_x1 = min_right - cushion
            if new_x1 > x1:
                # Thành công mở rộng sang phải
                return fitz.Rect(x0, y0, new_x1, y1)

        # Fallback: Mở rộng DỌC xuống dưới
        target_h = max(h, font_size * 1.8)
        target_y1 = y0 + target_h

        # Tìm các phần tử chồng lấn ngang và nằm bên dưới
        bottom_boundaries = [page_y1]
        for ob in other_bboxes:
            ox0, oy0, ox1, oy1 = ob
            # Chồng lấn ngang
            if max(x0, ox0) < min(x1, ox1):
                # Nằm bên dưới
                if oy0 >= y1:
                    bottom_boundaries.append(oy0)

        min_bottom = min(bottom_boundaries)
        max_y1 = min_bottom - cushion
        new_y1 = min(target_y1, max_y1)

        if new_y1 > y1:
            # Thành công mở rộng xuống dưới
            return fitz.Rect(x0, y0, x1, new_y1)

        # Nếu không mở rộng được hướng nào, giữ nguyên bbox gốc
        return fitz.Rect(x0, y0, x1, y1)

    def _calculate_font_size(
        self,
        temp_page: fitz.Page,
        text: str,
        bbox: tuple[float, float, float, float],
        original_size: float,
        min_size: float,
        font_name: str,
        align: int = 0,
    ) -> float:
        """Tính toán cỡ chữ phù hợp nhất để văn bản fit trong bounding box.

        Bắt đầu từ original_size và giảm dần 0.5pt cho đến khi vừa
        hoặc chạm tới min_size.
        """
        rect = fitz.Rect(bbox)
        current_size = max(min_size, original_size)

        # Thử chèn ở font size hiện tại
        res = temp_page.insert_textbox(
            rect, text, fontsize=current_size, fontname=font_name, align=align
        )
        # res >= 0 nghĩa là text fit vừa
        if res >= 0:
            return current_size

        # Giảm dần cỡ chữ
        while current_size > min_size:
            current_size = max(min_size, current_size - 0.5)
            res = temp_page.insert_textbox(
                rect, text, fontsize=current_size, fontname=font_name, align=align
            )
            if res >= 0:
                return current_size
            if current_size == min_size:
                break

        return min_size
