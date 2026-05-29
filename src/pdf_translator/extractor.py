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
                    align = 0
                    font_family = "sans"
                    text_x0, text_y0, text_x1, text_y1 = None, None, None, None
                    
                    for raw_block in cell_raw_blocks:
                        if raw_block.get("type", 0) != 0:
                            continue
                        for line in raw_block.get("lines", []):
                            lbox = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
                            if text_x0 is None or lbox[0] < text_x0: text_x0 = lbox[0]
                            if text_y0 is None or lbox[1] < text_y0: text_y0 = lbox[1]
                            if text_x1 is None or lbox[2] > text_x1: text_x1 = lbox[2]
                            if text_y1 is None or lbox[3] > text_y1: text_y1 = lbox[3]

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
                        
                        tbox = (text_x0, text_y0, text_x1, text_y1) if text_x0 is not None else cell_bbox
                        align = self._detect_alignment(
                            block_bbox=tbox,
                            lines=[],
                            page_width=page.rect.width,
                            cell_bbox=cell_bbox,
                        )
                        font_family = self._classify_font_family(font_name)
                        
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
                        align=align,
                        font_family=font_family,
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

            # Kiểm tra xem có nên chia nhỏ block thành các block độc lập cho từng dòng hay không.
            # Ta chia nếu block có nhiều hơn 1 dòng, và thuộc các trường hợp:
            # 1. Có bất kỳ dòng nào chứa địa chỉ email.
            # 2. Hoặc block được căn giữa (align=1) và có các dòng chênh lệch độ rộng lớn (không phải paragraph).
            should_split = False
            if len(lines) > 1:
                # 1. Kiểm tra nếu có bất kỳ dòng nào chứa email
                has_email = False
                for line in lines:
                    line_spans = line.get("spans", [])
                    line_text = "".join(span.get("text", "") for span in line_spans)
                    if re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", line_text):
                        has_email = True
                        break
                
                if has_email:
                    should_split = True
                else:
                    # 2. Hoặc nếu block căn giữa (align == 1) và có các dòng chênh lệch độ rộng lớn
                    align_temp = self._detect_alignment(block_bbox=bbox, lines=lines, page_width=page.rect.width)
                    if align_temp == 1:
                        line_widths = []
                        for line in lines:
                            lbox = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
                            if lbox != (0.0, 0.0, 0.0, 0.0):
                                line_widths.append(lbox[2] - lbox[0])
                        if line_widths:
                            max_w = max(line_widths)
                            if max_w > 0:
                                for w in line_widths[:-1]:
                                    if w / max_w < 0.7:
                                        should_split = True
                                        break

            # Danh sách các nhóm dòng cần xử lý (mỗi nhóm tạo thành 1 TextBlock)
            lines_to_process: list[list[dict]] = []
            if should_split:
                # Mỗi dòng là 1 nhóm riêng
                for line in lines:
                    lines_to_process.append([line])
            else:
                # Toàn bộ block là 1 nhóm
                lines_to_process.append(lines)

            # Xử lý từng nhóm dòng
            for line_group in lines_to_process:
                # Tính bbox của nhóm dòng
                group_x0, group_y0, group_x1, group_y1 = None, None, None, None
                for line in line_group:
                    lbox = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
                    if lbox == (0.0, 0.0, 0.0, 0.0):
                        lbox = bbox
                    lx0, ly0, lx1, ly1 = lbox
                    if group_x0 is None or lx0 < group_x0: group_x0 = lx0
                    if group_y0 is None or ly0 < group_y0: group_y0 = ly0
                    if group_x1 is None or lx1 > group_x1: group_x1 = lx1
                    if group_y1 is None or ly1 > group_y1: group_y1 = ly1
                
                if group_x0 is None:
                    continue
                group_bbox = (group_x0, group_y0, group_x1, group_y1)

                block_text_parts: list[str] = []
                span_styles: list[tuple[tuple[str, float, int, bool, bool], int]] = []

                for line in line_group:
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
                    continue

                # Bỏ qua nếu block gốc là block viết dọc hoặc xoay dọc
                if self._is_block_vertical(raw_block):
                    logger.debug(
                        f"Bỏ qua block {block_id} trên trang {page.number} (phát hiện text dọc hoặc xoay dọc)"
                    )
                    continue

                # Gộp các dòng bằng khoảng trắng
                merged_text = " ".join(block_text_parts)
                cleaned_text = re.sub(r"\s+", " ", merged_text).strip()

                # Kiểm tra xem block có cần dịch hay không
                block_font_names = [style[0][0] for style in span_styles]
                if self._should_skip_block(cleaned_text, block_font_names):
                    logger.debug(
                        f"Bỏ qua block {block_id} trên trang {page.number}: '{cleaned_text}'"
                    )
                    continue

                if not span_styles:
                    continue

                style_weights: Counter[tuple[str, float, int, bool, bool]] = Counter()
                for style_key, weight in span_styles:
                    style_weights[style_key] += weight

                dominant_style, _ = style_weights.most_common(1)[0]
                font_name, font_size, color, is_bold, is_italic = dominant_style

                align = self._detect_alignment(
                    block_bbox=group_bbox,
                    lines=line_group,
                    page_width=page.rect.width,
                )
                font_family = self._classify_font_family(font_name)

                text_block = TextBlock(
                    block_id=block_id,
                    text=cleaned_text,
                    bbox=group_bbox,
                    font_size=font_size,
                    font_name=font_name,
                    color=color,
                    is_bold=is_bold,
                    is_italic=is_italic,
                    page_number=page.number,
                    align=align,
                    font_family=font_family,
                    line_count=len(line_group),
                )
                text_blocks.append(text_block)
                block_id += 1

        merged_blocks = self._merge_sibling_blocks(text_blocks)
        for idx, block in enumerate(merged_blocks):
            block.block_id = idx
        return merged_blocks

    def _merge_sibling_blocks(self, blocks: list[TextBlock]) -> list[TextBlock]:
        """Gộp các block văn bản liên tiếp thuộc cùng một đoạn văn."""
        if not blocks:
            return []

        # Sắp xếp các block theo tọa độ y0 trước, nếu bằng nhau thì theo x0
        sorted_blocks = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
        merged_blocks: list[TextBlock] = []

        i = 0
        while i < len(sorted_blocks):
            current = sorted_blocks[i]

            # Thử gộp các block tiếp theo vào current
            j = i + 1
            while j < len(sorted_blocks):
                next_block = sorted_blocks[j]

                # Điều kiện gộp:
                # 1. Cùng là block thường (không phải ô bảng)
                if current.is_table_cell or next_block.is_table_cell:
                    break

                # 2. Khoảng cách dọc nhỏ và không bị chồng lấn ngược quá mức
                vertical_gap = next_block.bbox[1] - current.bbox[3]
                max_allowed_gap = max(8.0, current.font_size * 0.8)

                # 3. Trùng khớp biên trái (x0) gần như tương đồng (lệch tối đa 8pt do thụt đầu dòng hoặc dấu ngoặc)
                x0_diff = abs(current.bbox[0] - next_block.bbox[0])

                # 4. Trùng khớp kiểu font
                same_style = (
                    current.font_family == next_block.font_family and
                    abs(current.font_size - next_block.font_size) <= 1.0
                )

                # 5. Kiểm tra ký tự kết thúc/bắt đầu của block:
                # Nếu block sau bắt đầu bằng ký tự đầu dòng list (bullet, số thứ tự, gạch đầu dòng), không gộp.
                is_next_list_start = re.match(
                    r'^\s*([•\-\*\u2022\u25e6\u25aa\u25ab]|\d+[\.)]|\[\d+\])',
                    next_block.text
                ) is not None

                ends_sentence = re.search(r'[.!?]["”]?\s*$', current.text) is not None
                starts_with_lowercase = next_block.text and next_block.text.strip() and next_block.text.strip()[0].islower()

                should_merge = False
                if (-3.0 <= vertical_gap <= max_allowed_gap) and same_style and not is_next_list_start:
                    if x0_diff < 8.0:
                        if not ends_sentence or starts_with_lowercase:
                            should_merge = True

                if should_merge:
                    # Tạo block gộp mới
                    new_bbox = (
                        min(current.bbox[0], next_block.bbox[0]),
                        min(current.bbox[1], next_block.bbox[1]),
                        max(current.bbox[2], next_block.bbox[2]),
                        max(current.bbox[3], next_block.bbox[3]),
                    )

                    # Cập nhật block hiện tại
                    current = TextBlock(
                        block_id=current.block_id,
                        text=current.text + " " + next_block.text,
                        bbox=new_bbox,
                        font_size=current.font_size,
                        font_name=current.font_name,
                        color=current.color,
                        is_bold=current.is_bold,
                        is_italic=current.is_italic,
                        page_number=current.page_number,
                        is_table_cell=False,
                        align=current.align,
                        font_family=current.font_family,
                        line_count=current.line_count + next_block.line_count,
                        semantic_role=current.semantic_role or next_block.semantic_role,
                        semantic_context=current.semantic_context or next_block.semantic_context,
                        region_id=current.region_id or next_block.region_id
                    )
                    j += 1
                else:
                    break

            merged_blocks.append(current)
            i = j

        return merged_blocks


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

    def _detect_alignment(
        self,
        block_bbox: tuple[float, float, float, float],
        lines: list,
        page_width: float,
        cell_bbox: tuple[float, float, float, float] | None = None,
    ) -> int:
        """Ước lượng định dạng căn lề của văn bản gốc (0=Trái/Đều hai bên, 1=Giữa, 2=Phải)."""
        if cell_bbox:
            cx0, cy0, cx1, cy1 = cell_bbox
            bx0, by0, bx1, by1 = block_bbox
            cell_w = cx1 - cx0
            block_w = bx1 - bx0
            if block_w <= 0:
                return 0
            left_margin = bx0 - cx0
            right_margin = cx1 - bx1
            
            # Nếu căn giữa trong ô bảng
            if abs(left_margin - right_margin) < max(2.0, cell_w * 0.05):
                return 1
            # Nếu căn phải trong ô bảng
            if right_margin < 3.0 and left_margin > 5.0:
                return 2
            return 0

        if not lines:
            return 0

        bx0, by0, bx1, by1 = block_bbox
        block_w = bx1 - bx0
        if block_w <= 0:
            return 0

        if len(lines) > 1:
            left_deltas = [line.get("bbox", (0, 0, 0, 0))[0] - bx0 for line in lines]
            right_deltas = [bx1 - line.get("bbox", (0, 0, 0, 0))[2] for line in lines]

            # 1. Kiểm tra căn đều 2 bên (Justify) trước tiên.
            # Định nghĩa: Tất cả dòng (trừ dòng cuối) đều sát cả hai lề trái và phải.
            # Chỉ áp dụng cho block có độ rộng đáng kể (block_w > 50.0).
            body_lines = lines[:-1]
            justify_threshold = 3.0
            if block_w > 50.0 and len(body_lines) >= 1:
                left_flush = all((line.get("bbox", (0, 0, 0, 0))[0] - bx0) < justify_threshold for line in body_lines)
                right_flush = all((bx1 - line.get("bbox", (0, 0, 0, 0))[2]) < justify_threshold for line in body_lines)
                if left_flush and right_flush:
                    return 0  # Căn đều hai bên -> Fallback về căn trái (LEFT=0)

            # 2. Kiểm tra căn trái (Left-flush): tất cả dòng bắt đầu gần mép trái block
            left_threshold = min(12.0, block_w * 0.10)  # Cho phép indent nhẹ (bullet, hanging indent) nhưng giới hạn theo block width
            body_left_flush = all(
                (line.get("bbox", (0, 0, 0, 0))[0] - bx0) < left_threshold 
                for line in lines
            )
            
            # Phát hiện thụt lề dòng đầu (First-line indent): Dòng đầu thụt lề, tất cả các dòng sau căn lề trái sát bx0.
            # Đối với block 2 dòng, cần thêm điều kiện dòng cuối không sát lề phải để tránh nhầm với căn phải.
            # Đối với block từ 3 dòng trở lên, việc tất cả các dòng từ dòng 2 trở đi sát lề trái là đủ để khẳng định căn trái.
            first_line_indented = (
                len(lines) > 1 
                and all((line.get("bbox", (0, 0, 0, 0))[0] - bx0) < 3.0 for line in lines[1:])
                and (len(lines) >= 3 or (bx1 - lines[-1].get("bbox", (0, 0, 0, 0))[2]) > 5.0)
            )

            if body_left_flush or first_line_indented:
                if first_line_indented:
                    return 0  # LEFT
                
                # Nếu tất cả dòng body flush left nhưng KHÔNG ĐỒNG THỜI flush right -> LEFT
                body_right_flush = all(
                    (bx1 - line.get("bbox", (0, 0, 0, 0))[2]) < justify_threshold 
                    for line in body_lines
                )
                if not body_right_flush:
                    return 0  # LEFT

            max_left_delta = max(left_deltas[:-1]) if len(left_deltas) > 1 else left_deltas[0]
            max_right_delta = max(right_deltas[:-1]) if len(right_deltas) > 1 else right_deltas[0]

            # 3. Kiểm tra căn giữa (Center): khoảng cách trung tâm các dòng tới trung tâm block
            center_block = (bx0 + bx1) / 2
            center_deltas = [
                abs((l.get("bbox", (0, 0, 0, 0))[0] + l.get("bbox", (0, 0, 0, 0))[2]) / 2 - center_block)
                for l in lines
            ]
            max_center_delta = max(center_deltas)

            # Thu hẹp ngưỡng center từ 8% xuống 6% để tránh nhận diện nhầm căn giữa
            if max_center_delta < block_w * 0.06:
                return 1

            # 4. Kiểm tra căn phải (Right)
            if max_right_delta < max(3.0, block_w * 0.05):
                return 2

            return 0
        else:
            # 1 dòng duy nhất
            line = lines[0]
            lx0, ly0, lx1, ly1 = line.get("bbox", (0, 0, 0, 0))
            line_w = lx1 - lx0
            if line_w <= 0:
                return 0

            # Căn phải: nằm gần biên phải trang
            if page_width - lx1 < 70.0 and lx0 > page_width / 2:
                return 2

            # Căn giữa: trung tâm dòng nằm gần trung tâm trang và chiều rộng không phủ hết trang
            page_center = page_width / 2
            line_center = (lx0 + lx1) / 2
            if abs(line_center - page_center) < 20.0 and line_w < page_width * 0.6:
                return 1

            return 0

    def _classify_font_family(self, font_name: str) -> str:
        """Phân loại họ font chữ từ tên font (sans, serif, mono)."""
        name_lower = font_name.lower()
        if any(x in name_lower for x in ["courier", "mono", "consolas", "code", "fixed", "tele"]):
            return "mono"
        if any(x in name_lower for x in ["times", "serif", "georgia", "garamond", "cambria", "minion"]):
            return "serif"
        return "sans"
