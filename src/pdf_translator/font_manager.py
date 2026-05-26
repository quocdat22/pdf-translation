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
    """Quản lý font chữ cho việc render text dịch lên PDF.

    Hỗ trợ 3 họ font (sans, serif, mono) với 4 variants (Regular, Bold, Italic, BoldItalic):
    - sans: Sử dụng Noto Sans được bundle trong assets/fonts/
    - serif: Thử dùng Times New Roman hệ thống, fallback về Noto Sans
    - mono: Thử dùng Courier New hệ thống, fallback về Noto Sans

    Nếu user cung cấp custom_font_path, sẽ dùng font đó thay cho Noto Sans Regular.
    """

    # Tên font được đăng ký với PyMuPDF (dùng khi insert_textbox)
    FONT_NAMES = {
        ("sans", False, False): "NotoSans",
        ("sans", True, False): "NotoSansBold",
        ("sans", False, True): "NotoSansItalic",
        ("sans", True, True): "NotoSansBoldItalic",
        ("serif", False, False): "TimesNewRoman",
        ("serif", True, False): "TimesNewRomanBold",
        ("serif", False, True): "TimesNewRomanItalic",
        ("serif", True, True): "TimesNewRomanBoldItalic",
        ("mono", False, False): "CourierNew",
        ("mono", True, False): "CourierNewBold",
        ("mono", False, True): "CourierNewItalic",
        ("mono", True, True): "CourierNewBoldItalic",
    }

    def __init__(self, custom_font_path: str | None = None) -> None:
        """Khởi tạo FontManager.

        Args:
            custom_font_path: Đường dẫn đến font tùy chỉnh (Regular variant của Sans).
                Nếu None, dùng NotoSans-Regular.ttf từ bundle.
        """
        self._custom_font_path: Path | None = (
            Path(custom_font_path) if custom_font_path else None
        )
        self._font_paths: dict[tuple[str, bool, bool], Path] = {}
        self._validate_and_resolve_fonts()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_font_path(
        self,
        family: str = "sans",
        is_bold: bool = False,
        is_italic: bool = False,
    ) -> Path:
        """Trả về đường dẫn file font cho variant chỉ định.

        Args:
            family: Họ font ("sans", "serif", "mono").
            is_bold: True nếu muốn variant Bold.
            is_italic: True nếu muốn variant Italic.

        Returns:
            Path đến file .ttf.
        """
        key = (family, is_bold, is_italic)
        return self._font_paths[key]

    def register_font(
        self,
        page: fitz.Page,
        family: str = "sans",
        is_bold: bool = False,
        is_italic: bool = False,
    ) -> str:
        """Đăng ký font vào trang PDF và trả về tên font.

        PyMuPDF yêu cầu đăng ký font trước khi dùng insert_textbox.
        Mỗi trang cần đăng ký riêng.

        Args:
            page: Trang PDF (fitz.Page) sẽ đăng ký font vào.
            family: Họ font ("sans", "serif", "mono").
            is_bold: True để dùng variant Bold.
            is_italic: True để dùng variant Italic.

        Returns:
            Tên font (fontname) để truyền vào insert_textbox().

        Raises:
            RuntimeError: Nếu không thể đọc/đăng ký font.
        """
        key = (family, is_bold, is_italic)
        font_path = self._font_paths[key]
        font_name = self.FONT_NAMES[key]

        try:
            font_data = font_path.read_bytes()
            page.insert_font(fontname=font_name, fontbuffer=font_data)
            logger.debug(
                f"Đã đăng ký font '{font_name}' "
                f"(family={family}, bold={is_bold}, italic={is_italic}) cho page {page.number}"
            )
            return font_name
        except Exception as e:
            raise RuntimeError(
                f"Không thể đăng ký font '{font_path}': {e}"
            ) from e

    def get_regular_font_path(self) -> Path:
        """Trả về đường dẫn font Noto Sans Regular."""
        return self._font_paths[("sans", False, False)]

    def get_bold_font_path(self) -> Path:
        """Trả về đường dẫn font Noto Sans Bold."""
        return self._font_paths[("sans", True, False)]

    def get_italic_font_path(self) -> Path:
        """Trả về đường dẫn font Noto Sans Italic."""
        return self._font_paths[("sans", False, True)]

    def get_bold_italic_font_path(self) -> Path:
        """Trả về đường dẫn font Noto Sans BoldItalic."""
        return self._font_paths[("sans", True, True)]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate_and_resolve_fonts(self) -> None:
        """Resolve và validate đường dẫn tất cả font families và variants."""
        # 1. Resolve Sans (Noto Sans - bundled)
        regular_path = (
            self._custom_font_path
            if self._custom_font_path
            else BUNDLED_FONT_DIR / "NotoSans-Regular.ttf"
        )
        if not regular_path.exists():
            raise FileNotFoundError(
                f"Không tìm thấy font Regular: '{regular_path}'. "
                f"Hãy chạy script download font hoặc cung cấp đường dẫn font tùy chỉnh."
            )
        self._font_paths[("sans", False, False)] = regular_path
        logger.debug(f"Font Regular: {regular_path}")

        bundled_files = {
            (True, False): "NotoSans-Bold.ttf",
            (False, True): "NotoSans-Italic.ttf",
            (True, True): "NotoSans-BoldItalic.ttf",
        }
        for variant_key, file_name in bundled_files.items():
            is_bold, is_italic = variant_key
            bundle_path = BUNDLED_FONT_DIR / file_name
            if bundle_path.exists():
                self._font_paths[("sans", is_bold, is_italic)] = bundle_path
                logger.debug(f"Font NotoSans (bold={is_bold}, italic={is_italic}): {bundle_path}")
            else:
                logger.warning(f"Không tìm thấy font '{file_name}', fallback về Regular.")
                self._font_paths[("sans", is_bold, is_italic)] = regular_path

        # 2. Resolve Serif và Mono từ hệ thống, fallback về Sans tương ứng nếu thiếu
        for family in ["serif", "mono"]:
            for is_bold in [False, True]:
                for is_italic in [False, True]:
                    sys_font_path = self._resolve_system_font(family, is_bold, is_italic)
                    if sys_font_path and sys_font_path.exists():
                        self._font_paths[(family, is_bold, is_italic)] = sys_font_path
                        logger.debug(
                            f"Font hệ thống {family} (bold={is_bold}, italic={is_italic}): {sys_font_path}"
                        )
                    else:
                        # Fallback về Sans tương ứng
                        fallback_path = self._font_paths[("sans", is_bold, is_italic)]
                        self._font_paths[(family, is_bold, is_italic)] = fallback_path
                        logger.debug(
                            f"Không tìm thấy font hệ thống cho {family} (bold={is_bold}, italic={is_italic}), "
                            f"fallback về Noto Sans."
                        )

    def _resolve_system_font(
        self, family: str, is_bold: bool, is_italic: bool
    ) -> Path | None:
        """Tìm đường dẫn font hệ thống chuẩn cho Windows, macOS và Linux."""
        import sys
        key = (is_bold, is_italic)

        if sys.platform == "win32":
            fonts_dir = Path("C:/Windows/Fonts")
            if family == "serif":
                names = {
                    (False, False): "times.ttf",
                    (True, False): "timesbd.ttf",
                    (False, True): "timesi.ttf",
                    (True, True): "timesbi.ttf",
                }
                p = fonts_dir / names[key]
                return p if p.exists() else None
            elif family == "mono":
                names = {
                    (False, False): "cour.ttf",
                    (True, False): "courbd.ttf",
                    (False, True): "couri.ttf",
                    (True, True): "courbi.ttf",
                }
                p = fonts_dir / names[key]
                return p if p.exists() else None

        elif sys.platform == "darwin":
            search_dirs = [
                Path("/Library/Fonts"),
                Path("/System/Library/Fonts"),
                Path("/System/Library/Fonts/Supplemental"),
                Path("~/Library/Fonts").expanduser(),
            ]
            if family == "serif":
                files = {
                    (False, False): "Times New Roman.ttf",
                    (True, False): "Times New Roman Bold.ttf",
                    (False, True): "Times New Roman Italic.ttf",
                    (True, True): "Times New Roman Bold Italic.ttf",
                }
            elif family == "mono":
                files = {
                    (False, False): "Courier New.ttf",
                    (True, False): "Courier New Bold.ttf",
                    (False, True): "Courier New Italic.ttf",
                    (True, True): "Courier New Bold Italic.ttf",
                }
            else:
                return None

            for d in search_dirs:
                p = d / files[key]
                if p.exists():
                    return p

        elif sys.platform.startswith("linux"):
            return self._find_linux_font(family, is_bold, is_italic)

        return None

    def _find_linux_font(
        self, family: str, is_bold: bool, is_italic: bool
    ) -> Path | None:
        """Quét tìm font Linux phù hợp cho Serif hoặc Monospace."""
        search_dirs = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]

        keywords = []
        if family == "serif":
            keywords = ["times", "LiberationSerif", "DejaVuSerif"]
        elif family == "mono":
            keywords = ["courier", "LiberationMono", "DejaVuSansMono", "NotoMono"]

        for base_dir in search_dirs:
            if not base_dir.exists():
                continue
            for p in base_dir.rglob("*.ttf"):
                p_name_lower = p.name.lower()
                has_kw = any(kw.lower() in p_name_lower for kw in keywords)
                if not has_kw:
                    continue
                if is_bold and is_italic:
                    if "bolditalic" in p_name_lower or "bi" in p_name_lower or ("bold" in p_name_lower and "italic" in p_name_lower):
                        return p
                elif is_bold:
                    if "bold" in p_name_lower or "bd" in p_name_lower or "b.ttf" in p_name_lower:
                        if "italic" not in p_name_lower:
                            return p
                elif is_italic:
                    if "italic" in p_name_lower or "it" in p_name_lower or "i.ttf" in p_name_lower:
                        if "bold" not in p_name_lower:
                            return p
                else:
                    if any(x in p_name_lower for x in ["regular", "normal", "reg"]):
                        if "bold" not in p_name_lower and "italic" not in p_name_lower:
                            return p
                    if not any(x in p_name_lower for x in ["bold", "italic", "bd", "bi", "light", "medium"]):
                        return p
        return None
