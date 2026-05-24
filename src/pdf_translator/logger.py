"""
Logger setup cho pdf_translator.

Cung cấp:
- Console handler: colored output (INFO+)
- File handler: detailed output với timestamp (DEBUG+) — tuỳ chọn
- Logger name: "pdf_translator" (root logger của package)
"""

from __future__ import annotations

import logging
import sys
from typing import Optional


def setup_logger(level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """Cấu hình và trả về logger chính của ứng dụng.

    Gọi hàm này một lần khi khởi động CLI. Sau đó, các module khác
    chỉ cần gọi `get_logger()` để lấy logger đã được cấu hình.

    Args:
        level: Mức log cho console handler (DEBUG/INFO/WARNING/ERROR).
        log_file: Đường dẫn file log. Nếu None, chỉ log ra console.

    Returns:
        Logger đã được cấu hình.
    """
    logger = logging.getLogger("pdf_translator")

    # Tránh thêm duplicate handlers khi gọi lại nhiều lần
    if logger.handlers:
        logger.handlers.clear()

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(logging.DEBUG)  # Logger root bắt tất cả; handlers tự lọc

    # ----- Console handler -----
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(_build_console_formatter())
    logger.addHandler(console_handler)

    # ----- File handler (tuỳ chọn) -----
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(_build_file_formatter())
            logger.addHandler(file_handler)
        except OSError as e:
            logger.warning(f"Không thể tạo file log '{log_file}': {e}")

    return logger


def get_logger(name: str = "pdf_translator") -> logging.Logger:
    """Lấy logger theo tên (mặc định là root logger của package).

    Dùng trong các module con:
        logger = get_logger(__name__)

    Args:
        name: Tên logger. Nên dùng __name__ để có hierarchical logging.

    Returns:
        logging.Logger instance.
    """
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_console_formatter() -> logging.Formatter:
    """Tạo formatter cho console output.

    Format: HH:MM:SS │ LEVEL   │ message
    """
    return logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_file_formatter() -> logging.Formatter:
    """Tạo formatter cho file output (chi tiết hơn console).

    Format: ISO timestamp │ LEVEL   │ logger.name │ message
    """
    return logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
