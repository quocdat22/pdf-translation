"""Unit tests cho FontManager."""

from __future__ import annotations

import sys
from pathlib import Path
import fitz
import pytest

from pdf_translator.font_manager import FontManager


def test_font_manager_initialization() -> None:
    """Test khởi tạo FontManager thành công và gán đúng các font mặc định."""
    fm = FontManager()
    
    # Đảm bảo các font Noto Sans mặc định tồn tại và có đường dẫn hợp lệ
    sans_regular = fm.get_regular_font_path()
    assert sans_regular.exists()
    assert sans_regular.name == "NotoSans-Regular.ttf"

    assert fm.get_bold_font_path().exists()
    assert fm.get_italic_font_path().exists()
    assert fm.get_bold_italic_font_path().exists()

    # Kiểm tra phương thức get_font_path
    path = fm.get_font_path("sans", False, False)
    assert path == sans_regular


def test_font_manager_custom_font(tmp_path: Path) -> None:
    """Test dùng font tùy chỉnh."""
    # Custom font không tồn tại -> báo lỗi
    non_existent = tmp_path / "does_not_exist.ttf"
    with pytest.raises(FileNotFoundError):
        FontManager(custom_font_path=str(non_existent))

    # Tạo một file ttf giả để test
    custom_ttf = tmp_path / "custom.ttf"
    custom_ttf.write_text("dummy font data")
    
    fm = FontManager(custom_font_path=str(custom_ttf))
    assert fm.get_regular_font_path() == custom_ttf


def test_font_manager_register_font() -> None:
    """Test đăng ký font vào page fitz."""
    fm = FontManager()
    doc = fitz.open()
    page = doc.new_page()

    font_name = fm.register_font(page, "sans", is_bold=False, is_italic=False)
    assert font_name == "NotoSans"

    # Gây ra lỗi khi đọc font (mock bằng cách xóa hoặc thay đổi font_path thành thư mục)
    # Ta có thể mock `_font_paths` để chứa đường dẫn không hợp lệ
    fm._font_paths[("sans", False, False)] = Path("invalid_directory/non_existent_file.ttf")
    with pytest.raises(RuntimeError) as exc_info:
        fm.register_font(page, "sans", is_bold=False, is_italic=False)
    assert "Không thể đăng ký font" in str(exc_info.value)
    doc.close()


def test_resolve_system_font_win32(monkeypatch) -> None:
    """Test resolve font trên Windows."""
    # Giả lập platform là win32
    monkeypatch.setattr(sys, "platform", "win32")

    # Giả lập đường dẫn C:/Windows/Fonts/times.ttf tồn tại
    original_exists = Path.exists
    def mock_exists(self_path):
        if str(self_path).replace("\\", "/").endswith("Windows/Fonts/times.ttf"):
            return True
        if str(self_path).replace("\\", "/").endswith("Windows/Fonts/cour.ttf"):
            return True
        return original_exists(self_path)

    monkeypatch.setattr(Path, "exists", mock_exists)

    fm = FontManager()
    
    # Kiểm tra xem times.ttf có được resolve cho serif ko
    serif_path = fm._resolve_system_font("serif", False, False)
    assert serif_path is not None
    assert serif_path.name == "times.ttf"

    mono_path = fm._resolve_system_font("mono", False, False)
    assert mono_path is not None
    assert mono_path.name == "cour.ttf"


def test_resolve_system_font_darwin(monkeypatch) -> None:
    """Test resolve font trên macOS."""
    monkeypatch.setattr(sys, "platform", "darwin")

    # Giả lập một trong những thư mục fonts của macOS chứa Times New Roman.ttf và Courier New.ttf
    original_exists = Path.exists
    def mock_exists(self_path):
        path_str = str(self_path).replace("\\", "/")
        if "Library/Fonts/Times New Roman.ttf" in path_str:
            return True
        if "Library/Fonts/Courier New.ttf" in path_str:
            return True
        return original_exists(self_path)

    monkeypatch.setattr(Path, "exists", mock_exists)

    fm = FontManager()
    
    serif_path = fm._resolve_system_font("serif", False, False)
    assert serif_path is not None
    assert serif_path.name == "Times New Roman.ttf"

    mono_path = fm._resolve_system_font("mono", False, False)
    assert mono_path is not None
    assert mono_path.name == "Courier New.ttf"


def test_resolve_system_font_linux(monkeypatch) -> None:
    """Test resolve font trên Linux."""
    monkeypatch.setattr(sys, "platform", "linux")

    # Mock rglob trên các thư mục font Linux để trả về danh sách font giả lập
    mock_files = [
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationMono-Italic.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationMono-BoldItalic.ttf"),
    ]

    def mock_rglob(self, pattern):
        if pattern == "*.ttf":
            return mock_files
        return []

    original_exists = Path.exists
    def mock_exists(self_path):
        if str(self_path).replace("\\", "/").startswith("/usr/share/fonts"):
            return True
        return original_exists(self_path)

    monkeypatch.setattr(Path, "exists", mock_exists)
    monkeypatch.setattr(Path, "rglob", mock_rglob)

    fm = FontManager()

    # Serif
    serif_reg = fm._resolve_system_font("serif", False, False)
    assert serif_reg is not None
    assert serif_reg.name == "LiberationSerif-Regular.ttf"

    serif_bold = fm._resolve_system_font("serif", True, False)
    assert serif_bold is not None
    assert serif_bold.name == "LiberationSerif-Bold.ttf"

    serif_italic = fm._resolve_system_font("serif", False, True)
    assert serif_italic is not None
    assert serif_italic.name == "LiberationSerif-Italic.ttf"

    serif_bi = fm._resolve_system_font("serif", True, True)
    assert serif_bi is not None
    assert serif_bi.name == "LiberationSerif-BoldItalic.ttf"

    # Mono
    mono_reg = fm._resolve_system_font("mono", False, False)
    assert mono_reg is not None
    assert mono_reg.name == "LiberationMono-Regular.ttf"

    mono_bold = fm._resolve_system_font("mono", True, False)
    assert mono_bold is not None
    assert mono_bold.name == "LiberationMono-Bold.ttf"

    mono_italic = fm._resolve_system_font("mono", False, True)
    assert mono_italic is not None
    assert mono_italic.name == "LiberationMono-Italic.ttf"

    mono_bi = fm._resolve_system_font("mono", True, True)
    assert mono_bi is not None
    assert mono_bi.name == "LiberationMono-BoldItalic.ttf"


def test_font_manager_fallback(monkeypatch) -> None:
    """Test fallback về Noto Sans khi không tìm thấy font hệ thống."""
    # Force platform to Linux, but mock exists/rglob to find nothing
    monkeypatch.setattr(sys, "platform", "linux")
    
    original_exists = Path.exists
    def mock_exists(self_path):
        path_str = str(self_path).replace("\\", "/")
        if "fonts/NotoSans" in path_str:
            return True
        return False

    monkeypatch.setattr(Path, "exists", mock_exists)

    # Khởi tạo font manager -> Serif và Mono sẽ bị fallback về Sans
    fm = FontManager()

    # Đường dẫn của Serif Regular sẽ bằng với Sans Regular
    assert fm.get_font_path("serif", False, False) == fm.get_font_path("sans", False, False)
    # Đường dẫn của Mono Bold sẽ bằng với Sans Bold
    assert fm.get_font_path("mono", True, False) == fm.get_font_path("sans", True, False)
