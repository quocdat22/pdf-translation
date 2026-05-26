"""
Translation Cache — Lưu trữ và truy vấn bản dịch bằng SQLite.

Giúp tiết kiệm chi phí gọi API và tăng tốc độ xử lý khi dịch lại
các đoạn văn bản đã dịch trước đó.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from pdf_translator.logger import get_logger

logger = get_logger(__name__)


class TranslationCache:
    """Lưu trữ cục bộ các bản dịch sử dụng SQLite."""

    def __init__(self, db_path: Path) -> None:
        """Khởi tạo TranslationCache.

        Args:
            db_path: Đường dẫn đến file cơ sở dữ liệu SQLite.
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Khởi tạo cấu trúc bảng nếu chưa tồn tại."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS translations (
                        key TEXT PRIMARY KEY,
                        original_text TEXT,
                        translated_text TEXT,
                        source_lang TEXT,
                        target_lang TEXT,
                        model TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
        except Exception as e:
            logger.warning(
                f"Không thể khởi tạo cache database tại {self.db_path}: {e}"
            )

    def _make_key(
        self, text: str, source_lang: str, target_lang: str, model: str
    ) -> str:
        """Tạo khóa hash SHA256 duy nhất từ text và cấu hình dịch."""
        payload = f"{source_lang}:{target_lang}:{model}:{text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(
        self, text: str, source_lang: str, target_lang: str, model: str
    ) -> str | None:
        """Lấy bản dịch từ cache nếu tồn tại.

        Args:
            text: Văn bản gốc tiếng Anh.
            source_lang: Ngôn ngữ nguồn.
            target_lang: Ngôn ngữ đích.
            model: Tên mô hình LLM.

        Returns:
            Văn bản đã dịch nếu tìm thấy, ngược lại None.
        """
        key = self._make_key(text, source_lang, target_lang, model)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT translated_text FROM translations WHERE key = ?",
                    (key,),
                )
                row = cursor.fetchone()
                if row:
                    return str(row[0])
        except Exception as e:
            logger.warning(f"Lỗi khi đọc cache dịch thuật: {e}")
        return None

    def set(
        self,
        text: str,
        translated: str,
        source_lang: str,
        target_lang: str,
        model: str,
    ) -> None:
        """Ghi bản dịch vào cache database.

        Args:
            text: Văn bản gốc.
            translated: Bản dịch tiếng Việt.
            source_lang: Ngôn ngữ nguồn.
            target_lang: Ngôn ngữ đích.
            model: Tên mô hình LLM.
        """
        key = self._make_key(text, source_lang, target_lang, model)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO translations 
                    (key, original_text, translated_text, source_lang, target_lang, model)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (key, text, translated, source_lang, target_lang, model),
                )
        except Exception as e:
            logger.warning(f"Lỗi khi ghi cache dịch thuật: {e}")
