"""
Data models (dataclasses) cho pdf_translator.

Chứa các kiểu dữ liệu trung tâm được dùng xuyên suốt pipeline:
- TextBlock: text block được trích xuất từ PDF
- TranslatedBlock: text block đã dịch, kèm thông tin render
- TranslationResult: kết quả dịch một trang
- AppConfig: cấu hình ứng dụng
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TextBlock:
    """Một block text được trích xuất từ PDF.

    Attributes:
        block_id: ID duy nhất trong trang (thứ tự extract).
        text: Nội dung text gốc.
        bbox: Bounding box (x0, y0, x1, y1) theo tọa độ PDF (pt).
        font_size: Kích thước font dominant (pt).
        font_name: Tên font dominant gốc trong PDF.
        color: Màu chữ — tuple RGB float (0.0–1.0) hoặc int sRGB.
        is_bold: True nếu text block có style bold.
        is_italic: True nếu text block có style italic.
        page_number: Số trang (0-indexed).
    """

    block_id: int
    text: str
    bbox: tuple[float, float, float, float]
    font_size: float
    font_name: str
    color: tuple[float, float, float] | int
    is_bold: bool = False
    is_italic: bool = False
    page_number: int = 0
    is_table_cell: bool = False

    @property
    def width(self) -> float:
        """Chiều rộng bounding box (pt)."""
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        """Chiều cao bounding box (pt)."""
        return self.bbox[3] - self.bbox[1]

    @property
    def color_rgb(self) -> tuple[float, float, float]:
        """Màu chữ dạng RGB tuple float (0.0–1.0).

        Nếu color là int (sRGB packed: 0xRRGGBB), tự động chuyển đổi.
        """
        if isinstance(self.color, tuple):
            return self.color
        # int sRGB: 0xRRGGBB
        r = ((self.color >> 16) & 0xFF) / 255.0
        g = ((self.color >> 8) & 0xFF) / 255.0
        b = (self.color & 0xFF) / 255.0
        return (r, g, b)


@dataclass
class TranslatedBlock:
    """Block text đã được dịch, kèm thông tin render.

    Attributes:
        original: Block gốc (TextBlock).
        translated_text: Nội dung đã dịch sang tiếng Việt.
        adjusted_font_size: Font size sau khi auto-shrink (nếu cần).
    """

    original: TextBlock
    translated_text: str
    adjusted_font_size: float

    def __post_init__(self) -> None:
        """Đảm bảo adjusted_font_size không âm."""
        if self.adjusted_font_size <= 0:
            raise ValueError(
                f"adjusted_font_size phải > 0, nhận được: {self.adjusted_font_size}"
            )


@dataclass
class TranslationResult:
    """Kết quả dịch toàn bộ một trang.

    Attributes:
        page_number: Số trang (0-indexed).
        blocks: Danh sách các TranslatedBlock.
        success: True nếu dịch thành công.
        error: Thông báo lỗi (nếu success=False).
    """

    page_number: int
    blocks: list[TranslatedBlock] = field(default_factory=list)
    success: bool = True
    error: str | None = None


@dataclass
class AppConfig:
    """Cấu hình ứng dụng.

    Được nạp theo thứ tự ưu tiên:
    1. CLI arguments
    2. Environment variables (tiền tố PDF_TRANSLATOR_)
    3. File config TOML (config.toml ở thư mục gốc của dự án)
    4. Giá trị mặc định bên dưới

    Attributes:
        api_key: DeepSeek API key.
        api_base_url: Base URL của API endpoint.
        model: Tên model LLM dùng để dịch.
        source_lang: Ngôn ngữ nguồn (mặc định: English).
        target_lang: Ngôn ngữ đích (mặc định: Vietnamese).
        concurrency: Số trang dịch song song tối đa.
        min_font_size: Font size tối thiểu khi auto-shrink (pt).
        font_path: Đường dẫn font tùy chỉnh (rỗng = dùng Noto Sans bundle).
        log_level: Mức log (DEBUG/INFO/WARNING/ERROR).
        log_file: Đường dẫn file log (None = chỉ log ra console).
    """

    api_key: str = ""
    api_base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    source_lang: str = "English"
    target_lang: str = "Vietnamese"
    concurrency: int = 5
    min_font_size: float = 6.0
    font_path: str = ""
    log_level: str = "INFO"
    log_file: str | None = None
