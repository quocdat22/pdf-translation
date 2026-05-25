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
        
        # 1. Phát hiện các bảng trên trang
        try:
            tables = page.find_tables()
            table_list = tables.tables if tables else []
        except Exception as e:
            logger.warning(f"Lỗi khi phát hiện bảng trên trang {page.number}: {e}")
            table_list = []

        block_id = 0

        # 2. Trích xuất text từ các ô trong bảng trước
        for table in table_list:
            for r_idx, row in enumerate(table.rows):
                for c_idx, cell_bbox in enumerate(row.cells):
                    if not cell_bbox:
                        continue
                    # Trích xuất chi tiết spans nằm trong ô này để lấy text và dominant style
                    clip_dict = page.get_text("dict", clip=cell_bbox)
                    cell_raw_blocks = clip_dict.get("blocks", [])
                    
                    block_text_parts: list[str] = []
                    span_styles: list[tuple[tuple[str, float, int, bool, bool], int]] = []
                    
                    for raw_block in cell_raw_blocks:
                        if raw_block.get("type", 0) != 0:
                            continue
                        for line in raw_block.get("lines", []):
                            line_spans = line.get("spans", [])
                            line_text_parts: list[str] = []
                            for span in line_spans:
                                text = span.get("text", "")
                                if not text:
                                    continue
                                line_text_parts.append(text)
                                
                                font_name = span.get("font", "Helvetica")
                                font_size = span.get("size", 10.0)
                                color = span.get("color", 0)
                                flags = span.get("flags", 0)
                                
                                is_bold = bool(flags & 16) or "bold" in font_name.lower()
                                is_italic = bool(flags & 2) or "italic" in font_name.lower() or "oblique" in font_name.lower()
                                
                                style_key = (font_name, font_size, color, is_bold, is_italic)
                                span_styles.append((style_key, len(text)))
                                
                            if line_text_parts:
                                line_text = "".join(line_text_parts)
                                block_text_parts.append(line_text)
                                
                    if not block_text_parts:
                        # Fallback nếu không trích xuất được span nào qua clip nhưng table.extract() có text
                        fallback_text = ""
                        try:
                            fallback_text = table.extract()[r_idx][c_idx]
                        except Exception:
                            pass
                        
                        if not fallback_text or not fallback_text.strip():
                            continue
                            
                        cleaned_text = fallback_text.strip()
                        if self._should_skip_block(cleaned_text):
                            continue
                            
                        font_name = "Helvetica"
                        font_size = 9.0
                        color = 0
                        is_bold = False
                        is_italic = False
                    else:
                        merged_text = " ".join(block_text_parts)
                        cleaned_text = re.sub(r"\s+", " ", merged_text).strip()
                        
                        cell_font_names = [style[0][0] for style in span_styles]
                        if self._should_skip_block(cleaned_text, cell_font_names):
                            continue
                            
                        # Xác định dominant style
                        style_weights: Counter[tuple[str, float, int, bool, bool]] = Counter()
                        for style_key, weight in span_styles:
                            style_weights[style_key] += weight
                        
                        dominant_style, _ = style_weights.most_common(1)[0]
                        font_name, font_size, color, is_bold, is_italic = dominant_style
                        
                    # Tạo TextBlock cho ô bảng
                    text_block = TextBlock(
                        block_id=block_id,
                        text=cleaned_text,
                        bbox=cell_bbox,
                        font_size=font_size,
                        font_name=font_name,
                        color=color,
                        is_bold=is_bold,
                        is_italic=is_italic,
                        page_number=page.number,
                        is_table_cell=True,
                    )
                    text_blocks.append(text_block)
                    block_id += 1

        # 3. Trích xuất các block text thông thường ngoài bảng
        page_dict = page.get_text("dict")
        raw_blocks = page_dict.get("blocks", [])

        for raw_block in raw_blocks:
            # Chỉ xử lý text blocks (type == 0)
            if raw_block.get("type", 0) != 0:
                continue

            # Bỏ qua nếu block nằm trong bảng (đã được xử lý riêng biệt theo ô)
            bbox = raw_block.get("bbox", (0.0, 0.0, 0.0, 0.0))
            if self._is_inside_table(bbox, table_list):
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

            # Bỏ qua nếu block là block viết dọc hoặc xoay dọc (không nằm ngang bình thường)
            if self._is_block_vertical(raw_block):
                logger.debug(
                    f"Bỏ qua block {block_id} trên trang {page.number} (phát hiện text dọc hoặc xoay dọc)"
                )
                continue

            # Gộp các dòng lại bằng khoảng trắng để tránh ngắt từ làm LLM hiểu sai ngữ cảnh
            merged_text = " ".join(block_text_parts)

            # Làm sạch khoảng trắng dư thừa
            cleaned_text = re.sub(r"\s+", " ", merged_text).strip()

            # Kiểm tra xem block có cần dịch hay không
            block_font_names = [style[0][0] for style in span_styles]
            if self._should_skip_block(cleaned_text, block_font_names):
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

    def _is_block_vertical(self, raw_block: dict) -> bool:
        """Kiểm tra xem block text có hướng thẳng đứng (vertical) hoặc xoay dọc (rotated) hay không.

        Một block được coi là thẳng đứng nếu có ít nhất một dòng:
        1. Có writing mode là vertical (wmode == 1).
        2. Hoặc có vector hướng (dir) nghiêng về trục dọc nhiều hơn trục ngang (abs(dy) > abs(dx)).
        """
        for line in raw_block.get("lines", []):
            wmode = line.get("wmode", 0)
            if wmode == 1:
                return True

            direction = line.get("dir")
            if direction and len(direction) == 2:
                dx, dy = direction
                if abs(dy) > abs(dx):
                    return True

        return False


    def _is_math_block(self, text: str, font_names: list[str] | None = None) -> bool:
        """Kiểm tra xem block text có phải là biểu thức/ký tự toán học hay không."""
        stripped = text.strip()
        if not stripped:
            return False

        # 1. Kiểm tra Font chữ toán học
        math_font_pattern = re.compile(
            r"math|symbol|cmmi|cmsy|cmex|msam|msbm|euler|latex|katex|mtmi|mtsy|mtex|lgr|cbgreek",
            re.IGNORECASE
        )
        has_math_font = False
        if font_names:
            for font in font_names:
                if math_font_pattern.search(font):
                    has_math_font = True
                    break

        # 2. Kiểm tra ký hiệu toán học hoặc chữ Hy Lạp trong text
        math_or_greek_char_pattern = re.compile(
            r"["
            r"\u0370-\u03FF"       # Greek and Coptic
            r"\u1F00-\u1FFF"       # Greek Extended
            r"\u2100-\u214F"       # Letterlike Symbols
            r"\u2190-\u21FF"       # Arrows
            r"\u2200-\u22FF"       # Mathematical Operators
            r"\u27C0-\u27EF"       # Miscellaneous Mathematical Symbols-A
            r"\u2900-\u297F"       # Supplemental Arrows-B
            r"\u2980-\u29FF"       # Miscellaneous Mathematical Symbols-B
            r"\u2070-\u209F"       # Superscripts and Subscripts
            r"=+\-*/^<>≤≥≈≠±×÷"    # Standard math characters/operators
            r"]"
        )
        has_math_char = bool(math_or_greek_char_pattern.search(stripped))
        
        # Kiểm tra thêm Mathematical Alphanumeric Symbols (plane 1)
        if not has_math_char:
            for char in stripped:
                if 0x1D400 <= ord(char) <= 0x1D7FF:
                    has_math_char = True
                    break

        # 3. Đếm từ tiếng Anh bình thường (độ dài >= 3 và không thuộc MATH_KEYWORDS)
        words = re.findall(r"\b[a-zA-Z]{3,}\b", stripped)
        
        math_keywords = {
            # Các hàm toán học phổ biến
            "sin", "cos", "tan", "cot", "csc", "sec", "sinh", "cosh", "tanh", "coth",
            "log", "ln", "lg", "exp", "lim", "max", "min", "abs", "det", "inf", "sup",
            "arg", "deg", "dim", "extra", "ker", "var", "cov", "sgn", "mod", "div", "grad",
            "curl", "arc", "sqrt", "tr", "diag", "span", "rank",
            # Tên các chữ cái Hy Lạp
            "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
            "iota", "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma",
            "tau", "upsilon", "phi", "chi", "psi", "omega",
            # Các từ LaTeX phổ biến
            "frac", "left", "right", "begin", "end", "mathrm", "mathbf", "mathit",
            "quad", "qquad", "prod", "sum", "int", "diff", "partial"
        }
        
        normal_words = [w for w in words if w.lower() not in math_keywords]
        
        # Điều kiện xác định:
        # Nếu dùng font toán học OR có ký tự toán học, AND không có từ bình thường nào (normal_words = 0)
        if (has_math_font or has_math_char) and len(normal_words) == 0:
            return True

        return False

    def _should_skip_block(self, text: str, font_names: list[str] | None = None) -> bool:
        """Kiểm tra xem block text có nên bỏ qua hay không.

        Các trường hợp bỏ qua:
        1. Trống hoặc chỉ toàn khoảng trắng.
        2. Là biểu thức/ký tự toán học cần giữ nguyên chất lượng gốc.
        3. Không chứa bất kỳ ký tự chữ cái (a-zA-Z) nào.

        Args:
            text: Văn bản cần kiểm tra.
            font_names: Danh sách tên font của các span trong block.

        Returns:
            True nếu nên bỏ qua block này, ngược lại False.
        """
        stripped = text.strip()
        if not stripped:
            return True

        # Nếu là block toán học, bỏ qua để giữ nguyên gốc
        if self._is_math_block(stripped, font_names):
            return True

        # Nếu không có bất kỳ chữ cái tiếng Anh/Latin nào, thì bỏ qua không dịch.
        if not re.search(r"[a-zA-Z]", stripped):
            return True

        return False

    def _is_inside_table(
        self, bbox: tuple[float, float, float, float], table_list: list
    ) -> bool:
        """Kiểm tra xem bounding box có nằm trong (hoặc ghi đè nhiều lên) bất kỳ bảng nào không."""
        if not table_list:
            return False

        bx0, by0, bx1, by1 = bbox
        block_area = (bx1 - bx0) * (by1 - by0)
        if block_area <= 0:
            return False

        for table in table_list:
            tx0, ty0, tx1, ty1 = table.bbox
            # Tính phần giao nhau
            ix0 = max(bx0, tx0)
            iy0 = max(by0, ty0)
            ix1 = min(bx1, tx1)
            iy1 = min(by1, ty1)

            if ix0 < ix1 and iy0 < iy1:
                intersection_area = (ix1 - ix0) * (iy1 - iy0)
                if (intersection_area / block_area) > 0.5:
                    return True
        return False
