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
                    rect_to_use = self._get_expanded_rect(block.original.bbox, block.original.font_size)
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
                rect = self._get_expanded_rect(block.original.bbox, block.original.font_size)
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
        self, bbox: tuple[float, float, float, float], font_size: float
    ) -> fitz.Rect:
        """Tạo bounding box mở rộng để tránh việc co chữ quá mức hoặc mất chữ do giới hạn dòng.

        Mở rộng chiều cao xuống dưới dựa trên font size để đảm bảo đủ chiều cao dòng (line height)
        và nới rộng chiều rộng thêm 5% về phía bên phải để tránh tràn chiều ngang.
        """
        x0, y0, x1, y1 = bbox
        w = x1 - x0
        h = y1 - y0

        # Hệ số mở rộng chiều cao an toàn cho line-height của PyMuPDF
        new_h = max(h, font_size * 1.8)
        # Nới rộng chiều rộng thêm 5% để tạo khoảng trống thở cho bản dịch
        new_w = w + (w * 0.05)

        return fitz.Rect(x0, y0, x0 + new_w, y0 + new_h)

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
