"""Text Extractor — trích xuất văn bản từ PDF dùng PyMuPDF.

Trích xuất các text block từ trang PDF, gộp các line/span trong cùng một block,
và xác định các thuộc tính dominant (font name, font size, color, styles).
"""

from __future__ import annotations

import re
from collections import Counter
import fitz  # PyMuPDF

from pdf_translator.models import TextBlock
from pdf_translator.logger import get_logger

logger = get_logger(__name__)


class TextExtractor:
    """Trích xuất và chuẩn hóa các text block từ một trang PDF."""

    def __init__(self) -> None:
        pass

    def extract_page(self, page: fitz.Page) -> list[TextBlock]:
        """Trích xuất tất cả text blocks từ một trang PDF.

        Sử dụng page.get_text("dict") để lấy cấu trúc chi tiết:
        blocks -> lines -> spans.

        Args:
            page: Trang PDF (fitz.Page) cần trích xuất.

        Returns:
            Danh sách các TextBlock hợp lệ đã được gộp và làm sạch.
        """
        text_blocks: list[TextBlock] = []
        page_dict = page.get_text("dict")
        raw_blocks = page_dict.get("blocks", [])

        block_id = 0
        for raw_block in raw_blocks:
            # Chỉ xử lý text blocks (type == 0)
            if raw_block.get("type", 0) != 0:
                continue

            lines = raw_block.get("lines", [])
            if not lines:
                continue

            # Gộp toàn bộ spans của block thành nội dung text duy nhất
            # Thu thập tất cả các style (font, size, color, flags) từ spans để tìm style dominant
            block_text_parts: list[str] = []
            span_styles: list[tuple[tuple[str, float, int, bool, bool], int]] = []

            for line in lines:
                line_spans = line.get("spans", [])
                line_text_parts: list[str] = []
                for span in line_spans:
                    text = span.get("text", "")
                    if not text:
                        continue

                    line_text_parts.append(text)

                    # Thu thập metadata của span phục vụ xác định dominant style
                    # Cân trọng số theo độ dài của text trong span
                    font_name = span.get("font", "Helvetica")
                    font_size = span.get("size", 10.0)
                    color = span.get("color", 0)  # sRGB int
                    flags = span.get("flags", 0)

                    is_bold = bool(flags & 16) or "bold" in font_name.lower()
                    is_italic = bool(flags & 2) or "italic" in font_name.lower() or "oblique" in font_name.lower()

                    style_key = (font_name, font_size, color, is_bold, is_italic)
                    # Trọng số là độ dài của chuỗi
                    span_styles.append((style_key, len(text)))

                if line_text_parts:
                    line_text = "".join(line_text_parts)
                    block_text_parts.append(line_text)

            if not block_text_parts:
                continue

            # Gộp các dòng lại bằng khoảng trắng để tránh ngắt từ làm LLM hiểu sai ngữ cảnh
            merged_text = " ".join(block_text_parts)

            # Làm sạch khoảng trắng dư thừa
            cleaned_text = re.sub(r"\s+", " ", merged_text).strip()

            # Kiểm tra xem block có cần dịch hay không
            if self._should_skip_block(cleaned_text):
                logger.debug(
                    f"Bỏ qua block {block_id} trên trang {page.number}: '{cleaned_text}'"
                )
                continue

            # Xác định dominant style
            if not span_styles:
                continue

            # Tính tổng trọng số (độ dài ký tự) cho từng style
            style_weights: Counter[tuple[str, float, int, bool, bool]] = Counter()
            for style_key, weight in span_styles:
                style_weights[style_key] += weight

            dominant_style, _ = style_weights.most_common(1)[0]
            font_name, font_size, color, is_bold, is_italic = dominant_style

            # Bounding box của block
            bbox = raw_block.get("bbox", (0.0, 0.0, 0.0, 0.0))

            text_block = TextBlock(
                block_id=block_id,
                text=cleaned_text,
                bbox=bbox,
                font_size=font_size,
                font_name=font_name,
                color=color,
                is_bold=is_bold,
                is_italic=is_italic,
                page_number=page.number,
            )
            text_blocks.append(text_block)
            block_id += 1

        return text_blocks

    def _should_skip_block(self, text: str) -> bool:
        """Kiểm tra xem block text có nên bỏ qua hay không.

        Các trường hợp bỏ qua:
        1. Trống hoặc chỉ toàn khoảng trắng.
        2. Chỉ chứa số (ví dụ: '123', '45.6', '2026').
        3. Chỉ chứa các ký tự đặc biệt, ký hiệu hoặc dấu câu (ví dụ: '•', '—', '*', '...', '$, %').
        4. Không chứa bất kỳ ký tự chữ cái (a-zA-Z) nào.

        Args:
            text: Văn bản cần kiểm tra.

        Returns:
            True nếu nên bỏ qua block này, ngược lại False.
        """
        stripped = text.strip()
        if not stripped:
            return True

        # Nếu không có bất kỳ chữ cái tiếng Anh/Latin nào, thì bỏ qua không dịch.
        # Điều này loại bỏ các block chỉ có số, ký tự đặc biệt, ký hiệu toán học...
        # nhưng vẫn giữ các từ tiếng Anh ngắn.
        if not re.search(r"[a-zA-Z]", stripped):
            return True

        return False
