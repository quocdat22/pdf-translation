"""Unit tests cho TranslationCache."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pdf_translator.cache import TranslationCache


@pytest.fixture
def temp_db_path() -> Path:
    """Fixture tạo đường dẫn file SQLite tạm thời."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    # Dọn dẹp sau khi test xong
    try:
        if path.exists():
            path.unlink()
    except PermissionError:
        pass


def test_cache_init_and_operations(temp_db_path: Path) -> None:
    """Test khởi tạo cơ sở dữ liệu cache và các thao tác get/set cơ bản."""
    cache = TranslationCache(temp_db_path)

    # 1. Ban đầu cache trống
    val1 = cache.get("Hello world", "English", "Vietnamese", "deepseek-chat")
    assert val1 is None

    # 2. Ghi một bản dịch vào cache
    cache.set("Hello world", "Xin chào thế giới", "English", "Vietnamese", "deepseek-chat")

    # 3. Đọc lại từ cache
    val2 = cache.get("Hello world", "English", "Vietnamese", "deepseek-chat")
    assert val2 == "Xin chào thế giới"

    # 4. Đọc với tham số khác (model khác) -> miss cache
    val3 = cache.get("Hello world", "English", "Vietnamese", "gpt-4o")
    assert val3 is None

    # 5. Ghi đè bản dịch cũ
    cache.set("Hello world", "Chào thế giới", "English", "Vietnamese", "deepseek-chat")
    val4 = cache.get("Hello world", "English", "Vietnamese", "deepseek-chat")
    assert val4 == "Chào thế giới"
