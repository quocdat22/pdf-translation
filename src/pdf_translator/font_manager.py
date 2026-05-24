"""
Font Manager — quản lý font Noto Sans cho pdf_translator.

Font Noto Sans được bundle trong thư mục assets/fonts/ của package.
Hỗ trợ 4 variants: Regular, Bold, Italic, BoldItalic.

Tích hợp với PyMuPDF để đăng ký font vào từng trang PDF.
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from pdf_translator.logger import get_logger

logger = get_logger(__name__)

# Thư mục chứa font bundle, tính từ vị trí file này:
# src/pdf_translator/font_manager.py → project root → assets/fonts/
_THIS_DIR = Path(__file__).parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
BUNDLED_FONT_DIR = _PROJECT_ROOT / "assets" / "fonts"


class FontManager:
    """Quản lý font Noto Sans cho việc render text dịch lên PDF.

    Font được bundle trong package (assets/fonts/). Hỗ trợ 4 variants:
    - NotoSans-Regular.ttf
    - NotoSans-Bold.ttf
    - NotoSans-Italic.ttf
    - NotoSans-BoldItalic.ttf

    Nếu user cung cấp custom_font_path, sẽ dùng font đó thay cho Regular.
    Các variant Bold/Italic vẫn dùng bundle (nếu tồn tại).

    Usage:
        fm = FontManager()
        font_name = fm.register_font(page, is_bold=False, is_italic=False)
        # Dùng font_name với page.insert_textbox(...)
    """

    # Tên file của từng variant
    FONT_FILES = {
        (False, False): "NotoSans-Regular.ttf",
        (True, False): "NotoSans-Bold.ttf",
        (False, True): "NotoSans-Italic.ttf",
        (True, True): "NotoSans-BoldItalic.ttf",
    }

    # Tên font được đăng ký với PyMuPDF (dùng khi insert_textbox)
    FONT_NAMES = {
        (False, False): "NotoSans",
        (True, False): "NotoSansBold",
        (False, True): "NotoSansItalic",
        (True, True): "NotoSansBoldItalic",
    }

    def __init__(self, custom_font_path: str | None = None) -> None:
        """Khởi tạo FontManager.

        Args:
            custom_font_path: Đường dẫn đến font tùy chỉnh (Regular variant).
                Nếu None, dùng NotoSans-Regular.ttf từ bundle.

        Raises:
            FileNotFoundError: Nếu font Regular không tìm thấy.
        """
        self._custom_font_path: Path | None = (
            Path(custom_font_path) if custom_font_path else None
        )
        self._font_paths: dict[tuple[bool, bool], Path] = {}
        self._validate_and_resolve_fonts()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_font_path(self, is_bold: bool = False, is_italic: bool = False) -> Path:
        """Trả về đường dẫn file font cho variant chỉ định.

        Args:
            is_bold: True nếu muốn variant Bold.
            is_italic: True nếu muốn variant Italic.

        Returns:
            Path đến file .ttf.
        """
        key = (is_bold, is_italic)
        return self._font_paths[key]

    def register_font(
        self,
        page: fitz.Page,
        is_bold: bool = False,
        is_italic: bool = False,
    ) -> str:
        """Đăng ký font vào trang PDF và trả về tên font.

        PyMuPDF yêu cầu đăng ký font trước khi dùng insert_textbox.
        Mỗi trang cần đăng ký riêng.

        Args:
            page: Trang PDF (fitz.Page) sẽ đăng ký font vào.
            is_bold: True để dùng variant Bold.
            is_italic: True để dùng variant Italic.

        Returns:
            Tên font (fontname) để truyền vào insert_textbox().

        Raises:
            RuntimeError: Nếu không thể đọc/đăng ký font.
        """
        key = (is_bold, is_italic)
        font_path = self._font_paths[key]
        font_name = self.FONT_NAMES[key]

        try:
            font_data = font_path.read_bytes()
            page.insert_font(fontname=font_name, fontbuffer=font_data)
            logger.debug(
                f"Đã đăng ký font '{font_name}' "
                f"(bold={is_bold}, italic={is_italic}) cho page {page.number}"
            )
            return font_name
        except Exception as e:
            raise RuntimeError(
                f"Không thể đăng ký font '{font_path}': {e}"
            ) from e

    def get_regular_font_path(self) -> Path:
        """Trả về đường dẫn font Regular (có thể là custom)."""
        return self._font_paths[(False, False)]

    def get_bold_font_path(self) -> Path:
        """Trả về đường dẫn font Bold variant."""
        return self._font_paths[(True, False)]

    def get_italic_font_path(self) -> Path:
        """Trả về đường dẫn font Italic variant."""
        return self._font_paths[(False, True)]

    def get_bold_italic_font_path(self) -> Path:
        """Trả về đường dẫn font Bold+Italic variant."""
        return self._font_paths[(True, True)]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate_and_resolve_fonts(self) -> None:
        """Resolve và validate đường dẫn tất cả font variants.

        - Regular: custom_font_path nếu có, hoặc bundle NotoSans-Regular.ttf
        - Bold/Italic/BoldItalic: luôn dùng bundle (fallback về Regular nếu thiếu)

        Raises:
            FileNotFoundError: Nếu font Regular không tìm thấy.
        """
        # Regular
        regular_path = (
            self._custom_font_path
            if self._custom_font_path
            else BUNDLED_FONT_DIR / self.FONT_FILES[(False, False)]
        )
        if not regular_path.exists():
            raise FileNotFoundError(
                f"Không tìm thấy font Regular: '{regular_path}'. "
                f"Hãy chạy script download font hoặc cung cấp đường dẫn font tùy chỉnh."
            )
        self._font_paths[(False, False)] = regular_path
        logger.debug(f"Font Regular: {regular_path}")

        # Bold, Italic, BoldItalic — dùng bundle, fallback về Regular nếu thiếu
        for variant_key in [(True, False), (False, True), (True, True)]:
            bundle_path = BUNDLED_FONT_DIR / self.FONT_FILES[variant_key]
            if bundle_path.exists():
                self._font_paths[variant_key] = bundle_path
                logger.debug(
                    f"Font {self.FONT_NAMES[variant_key]}: {bundle_path}"
                )
            else:
                # Fallback về Regular — text vẫn hiển thị được
                logger.warning(
                    f"Không tìm thấy font '{bundle_path.name}', "
                    f"fallback về Regular."
                )
                self._font_paths[variant_key] = regular_path
